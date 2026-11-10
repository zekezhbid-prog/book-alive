import { Link } from 'react-router-dom'
import { useI18n, type Lang } from '../i18n'

interface Text {
  title: string
  lead: string
  whoTitle: string
  who: [string, string][]
  whatTitle: string
  what: [string, string][]
  startTitle: string
  start: string[]
  privacy: string
  toProjects: string
  toLogin: string
}

// Long prose, so it lives here rather than in the shared dictionaries.
const TEXT: Record<Lang, Text> = {
  ru: {
    title: 'Lorebook — справочник по вашей книге',
    lead:
      'Загрузите готовую книгу или пишите прямо здесь. Lorebook разобьёт текст на главы, соберёт карточки героев, мест и предметов с цитатами из текста, найдёт сцены и подготовит промпты для картинок и видео. Герой на десятой картинке будет похож на себя с первой.',
    whoTitle: 'Кому пригодится',
    who: [
      ['Писателям', 'Редактор с версиями всей книги, проверка грамматики, редактура и поиск противоречий: у героя не поменяется цвет глаз между пятой и двадцатой главой.'],
      ['Иллюстраторам и авторам видео', 'Внешность каждого героя собрана из книги в одну карточку, стиль выбирается один на весь проект, промпты готовы для генераторов картинок и видео.'],
      ['Читателям и фанатам', 'Энциклопедия мира книги и чат, который ответит, где впервые встретились двое героев, и даст ссылку на абзац.'],
    ],
    whatTitle: 'Что внутри',
    what: [
      ['Главы', 'TXT, EPUB, FB2, DOCX и PDF делятся на главы автоматически.'],
      ['Персонажи и локации', 'Карточки строятся по главам, каждый факт с цитатой. Можно дописать карточку вручную и приложить картинки.'],
      ['Сцены', 'Яркие моменты книги с готовыми промптами для кадра.'],
      ['Стиль', 'Общий вид всех картинок проекта и референсы.'],
      ['Чат по книге', 'Вопросы по всей книге или выбранным главам, ответы со ссылками на текст.'],
      ['Поиск', 'По всему тексту книги, с переходом к нужному месту.'],
    ],
    startTitle: 'Как начать',
    start: [
      'Создайте проект: загрузите книгу или начните с чистого листа.',
      'В Настройках выберите модели ИИ для задач.',
      'Запустите поиск персонажей — карточки появятся по мере чтения глав.',
    ],
    privacy: 'Проекты видны только в вашем аккаунте. Книги никуда не публикуются.',
    toProjects: 'Мои проекты',
    toLogin: 'Войти',
  },
  by: {
    title: 'Lorebook — даведнік па вашай кнізе',
    lead:
      'Загрузіце гатовую кнігу або пішыце проста тут. Lorebook разаб’е тэкст на раздзелы, збярэ карткі герояў, месцаў і рэчаў з цытатамі з тэксту, знойдзе сцэны і падрыхтуе промпты для малюнкаў і відэа. Герой на дзясятым малюнку будзе падобны на сябе з першага.',
    whoTitle: 'Каму спатрэбіцца',
    who: [
      ['Пісьменнікам', 'Рэдактар з версіямі ўсёй кнігі, праверка граматыкі, рэдактура і пошук супярэчнасцей: у героя не зменіцца колер вачэй паміж пятым і дваццатым раздзелам.'],
      ['Ілюстратарам і аўтарам відэа', 'Знешнасць кожнага героя сабрана з кнігі ў адну картку, стыль выбіраецца адзін на ўвесь праект, промпты гатовыя для генератараў малюнкаў і відэа.'],
      ['Чытачам і фанатам', 'Энцыклапедыя свету кнігі і чат, які адкажа, дзе ўпершыню сустрэліся двое герояў, і дасць спасылку на абзац.'],
    ],
    whatTitle: 'Што ўнутры',
    what: [
      ['Раздзелы', 'TXT, EPUB, FB2, DOCX і PDF дзеляцца на раздзелы аўтаматычна.'],
      ['Персанажы і лакацыі', 'Карткі будуюцца па раздзелах, кожны факт з цытатай. Картку можна дапісаць уручную і дадаць малюнкі.'],
      ['Сцэны', 'Яркія моманты кнігі з гатовымі промптамі для кадра.'],
      ['Стыль', 'Агульны выгляд усіх малюнкаў праекта і рэферэнсы.'],
      ['Чат па кнізе', 'Пытанні па ўсёй кнізе або выбраных раздзелах, адказы са спасылкамі на тэкст.'],
      ['Пошук', 'Па ўсім тэксце кнігі, з пераходам да патрэбнага месца.'],
    ],
    startTitle: 'Як пачаць',
    start: [
      'Стварыце праект: загрузіце кнігу або пачніце з чыстага аркуша.',
      'У Наладах выберыце мадэлі ШІ для задач.',
      'Запусціце пошук персанажаў — карткі з’явяцца па меры чытання раздзелаў.',
    ],
    privacy: 'Праекты бачныя толькі ў вашым акаўнце. Кнігі нікуды не публікуюцца.',
    toProjects: 'Мае праекты',
    toLogin: 'Увайсці',
  },
  en: {
    title: 'Lorebook — a guide to your book',
    lead:
      'Upload a finished book or write it right here. Lorebook splits the text into chapters, builds cards for characters, places and objects with quotes from the text, finds scenes and writes prompts for images and video. The hero in the tenth picture still looks like the hero in the first.',
    whoTitle: 'Who it is for',
    who: [
      ['Writers', 'An editor with versions of the whole book, grammar checks, editing notes and a contradiction finder: your hero’s eyes won’t change colour between chapter five and chapter twenty.'],
      ['Illustrators and video makers', 'Each character’s looks gathered from the book into one card, one style for the whole project, prompts ready for image and video generators.'],
      ['Readers and fans', 'An encyclopedia of the book’s world and a chat that tells you where two characters first met, with a link to the paragraph.'],
    ],
    whatTitle: 'What’s inside',
    what: [
      ['Chapters', 'TXT, EPUB, FB2, DOCX and PDF are split into chapters automatically.'],
      ['Characters and locations', 'Cards are built chapter by chapter, every fact with a quote. You can add to a card by hand and attach pictures.'],
      ['Scenes', 'The book’s vivid moments with prompts ready for a frame.'],
      ['Style', 'One look for every picture in the project, plus references.'],
      ['Book chat', 'Ask about the whole book or chosen chapters; answers link to the text.'],
      ['Search', 'Across the whole text, jumping straight to the place.'],
    ],
    startTitle: 'How to start',
    start: [
      'Create a project: upload a book or start from a blank page.',
      'In Settings, choose the AI models for each task.',
      'Run the character search — cards appear as the chapters are read.',
    ],
    privacy: 'Projects are visible only in your account. Books are never published anywhere.',
    toProjects: 'My projects',
    toLogin: 'Sign in',
  },
}

/** What Lorebook is, for whom and how to start: the page behind the Lorebook name. */
export default function About({ signedIn }: { signedIn: boolean }) {
  const { lang } = useI18n()
  const text = TEXT[lang]
  return (
    <main className="page narrow about">
      <h1>{text.title}</h1>
      <p className="about-lead">{text.lead}</p>

      <h2>{text.whoTitle}</h2>
      <div className="about-grid">
        {text.who.map(([name, body]) => (
          <div key={name} className="card">
            <h3>{name}</h3>
            <p className="muted">{body}</p>
          </div>
        ))}
      </div>

      <h2>{text.whatTitle}</h2>
      <dl className="about-list">
        {text.what.map(([name, body]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd className="muted">{body}</dd>
          </div>
        ))}
      </dl>

      <h2>{text.startTitle}</h2>
      <ol className="about-steps">
        {text.start.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>

      <p className="faint">{text.privacy}</p>
      <Link to="/" className="btn primary">
        {signedIn ? text.toProjects : text.toLogin}
      </Link>
    </main>
  )
}
