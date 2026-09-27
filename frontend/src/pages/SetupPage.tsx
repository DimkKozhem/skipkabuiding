import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";

const PATH = [
  { title: "Кадр", text: "Фото или видео с площадки становится наблюдением." },
  { title: "Наблюдение", text: "По кадру фиксируется то, что видно: этап, техника, конструктив." },
  { title: "Сравнение", text: "Наблюдение ставится рядом с графиком объекта. Сроки не выдумываются." },
  { title: "Проверка", text: "Сигнал просит инспектора посмотреть кадры. Решение остаётся за человеком." },
];

const DETAILS: { title: string; text: string }[] = [
  {
    title: "Как создать объект",
    text: "В шапке — «Добавить объект». После сохранения откроются источники: камера, файл или свой кадр. График задаётся отдельно.",
  },
  {
    title: "Как читать витрину",
    text: "Сверху объекты, которым нужна проверка. На карточке — последний кадр, план и факт. Если кадра нет, карточка так и пишет.",
  },
  {
    title: "Что такое сигнал",
    text: "Признак возможного отклонения: не видно ожидаемой техники или нет наблюдаемой динамики. Это не вывод о нарушении и не остановка работ.",
  },
];

export function SetupPage() {
  return (
    <div className="project-guide">
      <PageHeader
        title="Скрипка"
        lead="Контроль строительства: план из графика объекта и факт по кадрам. Система показывает признак и просит проверить. Итог не подменяет решение инспектора."
      />
      <ol className="guide-path">
        {PATH.map(step => (
          <li key={step.title}>
            <h2>{step.title}</h2>
            <p>{step.text}</p>
          </li>
        ))}
      </ol>
      <details className="guide-more">
        <summary>Как пользоваться</summary>
        <ol className="guide-list">
          {DETAILS.map(step => (
            <li key={step.title}>
              <div>
                <h2>{step.title}</h2>
                <p>{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </details>
      <p className="guide-next">
        Дальше — <Link to="/objects">объекты</Link>, <Link to="/signals">сигналы</Link> или <Link to="/objects/new">новый объект</Link>.
      </p>
    </div>
  );
}
