#!/usr/bin/env bash
# Tuna 0.27 часто не выходит сама после EOF/RST и публичный URL остаётся 404.
# Цикл перезапускает процесс; watchdog убивает зависший tuna, если локальный
# /health жив, а https://skipkabuiding.ru.tuna.am/health — нет.
set -u

TUNA="${TUNA_BIN:-/usr/bin/tuna}"
PORT="${TUNA_PORT:-8000}"
SUBDOMAIN="${TUNA_SUBDOMAIN:-skipkabuiding}"
LOCATION="${TUNA_LOCATION:-ru}"
HEALTH_URL="${TUNA_HEALTH_URL:-http://127.0.0.1:${PORT}/health}"
PUBLIC_HOST="${TUNA_PUBLIC_HOST:-${SUBDOMAIN}.ru.tuna.am}"
PUBLIC_HEALTH="${TUNA_PUBLIC_HEALTH:-https://${PUBLIC_HOST}/health}"
CHECK_EVERY="${TUNA_CHECK_EVERY:-10}"
FAILS_MAX="${TUNA_FAILS_MAX:-4}"
START_GRACE="${TUNA_START_GRACE:-25}"
BACKOFF="${TUNA_BACKOFF:-3}"
ACTIVE_WAIT="${TUNA_ACTIVE_WAIT:-45}"
QUICK_FAIL_SEC="${TUNA_QUICK_FAIL_SEC:-20}"
TUNA_LOG="${TUNA_LOG:-/tmp/sitewatch-tuna.log}"
RESOLV_FILE="${TUNA_RESOLV_FILE:-/tmp/sitewatch-tuna-resolv.conf}"

export HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= http_proxy= https_proxy= all_proxy=

curl_noproxy() {
  curl --noproxy '*' "$@"
}

log() {
  echo "$(date -Is) $*" >&2
}

lan_iface() {
  ip -4 route show table main default 2>/dev/null | awk '{print $5; exit}'
}

lan_dns() {
  local iface dns gw
  iface="$(lan_iface)"
  gw="$(ip -4 route show table main default 2>/dev/null | awk '{print $3; exit}')"
  dns=""
  if [[ -n "${iface}" ]]; then
    dns="$(resolvectl dns "${iface}" 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i ~ /^[0-9.]+$/) {print $i; exit}}')"
  fi
  echo "${dns:-${gw:-192.168.0.1}}"
}

resolve_public_ip() {
  local dns ip
  dns="$(lan_dns)"
  ip="$(dig +time=2 +tries=1 +short @"$dns" "$PUBLIC_HOST" A 2>/dev/null | awk '/^[0-9.]+$/ {print; exit}')"
  if [[ -z "${ip}" ]]; then
    ip="$(dig +time=2 +tries=1 +short @8.8.8.8 "$PUBLIC_HOST" A 2>/dev/null | awk '/^[0-9.]+$/ {print; exit}')"
  fi
  echo "${ip}"
}

local_ok() {
  curl_noproxy -sf --max-time 2 "$HEALTH_URL" 2>/dev/null | grep -q '"ok"'
}

wait_api() {
  local i
  for i in $(seq 1 60); do
    if local_ok; then
      return 0
    fi
    sleep 1
  done
  log "локальный ${HEALTH_URL} не ответил, стартую tuna всё равно"
  return 0
}

write_resolv() {
  local dns
  dns="$(lan_dns)"
  {
    echo "nameserver ${dns}"
    echo "nameserver 8.8.8.8"
    echo "options timeout:2 attempts:2 ndots:1"
  } >"$RESOLV_FILE"
}

public_curl() {
  local iface ip args
  iface="$(lan_iface)"
  ip="$(resolve_public_ip)"
  args=( -sS --max-time 6 )
  if [[ -n "${iface}" ]]; then
    args+=( --interface "${iface}" )
  fi
  if [[ -n "${ip}" ]]; then
    args+=( --resolve "${PUBLIC_HOST}:443:${ip}" )
  fi
  curl_noproxy "${args[@]}" "$PUBLIC_HEALTH"
}

# true, если публичный /health — это ответ Скрипки, а не страница «туннель не найден».
public_ok() {
  local body
  body="$(public_curl 2>/dev/null || true)"
  printf '%s' "$body" | grep -q '"ok"' && ! printf '%s' "$body" | grep -qi 'не найден'
}

kill_our_tuna() {
  local pids
  pids="$(pgrep -f "${TUNA} http ${PORT} --subdomain=${SUBDOMAIN}" 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    pids="$(pgrep -f "tuna http ${PORT} --subdomain=${SUBDOMAIN}" 2>/dev/null || true)"
  fi
  if [[ -n "${pids}" ]]; then
    log "останавливаю локальный tuna: ${pids}"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
  fi
  local i
  for i in $(seq 1 45); do
    if ! public_ok; then
      return 0
    fi
    sleep 1
  done
  log "публичный URL ещё отвечает после kill — жду освобождения слота"
  sleep 5
}

run_tuna() {
  write_resolv
  : >"$TUNA_LOG"
  if unshare --user --map-root-user --mount true 2>/dev/null; then
    unshare --user --map-root-user --mount bash -c \
      "mount --bind $(printf '%q' "$RESOLV_FILE") /etc/resolv.conf && exec $(printf '%q' "$TUNA") http $(printf '%q' "$PORT") --subdomain=$(printf '%q' "$SUBDOMAIN") --location=$(printf '%q' "$LOCATION")" \
      >"$TUNA_LOG" 2>&1
  else
    "$TUNA" http "$PORT" --subdomain="$SUBDOMAIN" --location="$LOCATION" >"$TUNA_LOG" 2>&1
  fi
}

wait_slot() {
  local reason="$1"
  local i
  log "ждём слот туннеля (${reason}), до ${ACTIVE_WAIT}s"
  for i in $(seq 1 "$ACTIVE_WAIT"); do
    if ! public_ok; then
      sleep 3
      return 0
    fi
    sleep 1
  done
  log "слот всё ещё занят — пробую снова"
}

watch_until_dead() {
  local pid="$1"
  local fails=0
  local started now age
  started="$(date +%s)"
  while kill -0 "$pid" 2>/dev/null; do
    now="$(date +%s)"
    age=$((now - started))
    if [[ "$age" -lt "$START_GRACE" ]]; then
      sleep 2
      continue
    fi
    if public_ok; then
      fails=0
    elif ! local_ok; then
      fails=0
      log "локальный ${HEALTH_URL} молчит, tuna не перезапускаю"
    else
      fails=$((fails + 1))
      log "публичный туннель не отвечает (${fails}/${FAILS_MAX}): ${PUBLIC_HEALTH}"
      if [[ "$fails" -ge "$FAILS_MAX" ]]; then
        log "watchdog: убиваю зависший tuna pid=${pid}"
        kill "$pid" 2>/dev/null || true
        sleep 1
        kill -9 "$pid" 2>/dev/null || true
        return 1
      fi
    fi
    sleep "$CHECK_EVERY"
  done
  return 0
}

cleanup() {
  trap - TERM INT
  kill_our_tuna
  exit 0
}
trap cleanup TERM INT

while true; do
  wait_api
  kill_our_tuna
  log "tuna start ${SUBDOMAIN} -> 127.0.0.1:${PORT}"
  started_at="$(date +%s)"
  run_tuna &
  tuna_pid=$!
  tail -n0 -F "$TUNA_LOG" 2>/dev/null &
  tail_pid=$!
  watch_until_dead "$tuna_pid" || true
  wait "$tuna_pid" 2>/dev/null || true
  kill "$tail_pid" 2>/dev/null || true
  wait "$tail_pid" 2>/dev/null || true
  lived=$(( $(date +%s) - started_at ))
  if grep -qi 'Tunnel already active' "$TUNA_LOG" 2>/dev/null; then
    wait_slot "Tunnel already active"
  elif [[ "$lived" -lt "$QUICK_FAIL_SEC" ]]; then
    wait_slot "быстрый выход ${lived}s"
  fi
  log "tuna exit (жил ${lived}s), reconnect in ${BACKOFF}s"
  sleep "$BACKOFF"
done
