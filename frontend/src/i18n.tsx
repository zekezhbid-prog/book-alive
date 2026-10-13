import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { ApiError } from './api'

export type Lang = 'ru' | 'en'

const ru = {
  'app.settings': 'Настройки',
  'app.projects': 'Проекты',
  'app.loading': 'Загрузка…',
  'app.cancel': 'Отмена',
  'app.delete': 'Удалить',
  'app.save': 'Сохранить',
  'app.saved': 'Сохранено',
  'app.saving': 'Сохраняю…',
  'app.chars': '{n} зн.',

  'projects.title': 'Проекты',
  'projects.new': 'Новый проект',
  'projects.empty': 'Проектов пока нет. Создайте первый: загрузите готовую книгу или начните писать свою.',
  'projects.chapters': 'глав: {n}',
  'projects.delete.confirm': 'Удалить проект «{title}» со всеми главами и версиями? Отменить это нельзя.',

  'mode.reader': 'Готовая книга',
  'mode.writer': 'Пишу книгу',
  'mode.reader.hint': 'Загружаете готовый текст. Он только читается; вы находите персонажей, локации и сцены и готовите их к оживлению.',
  'mode.writer.hint': 'Пишете и правите главы прямо здесь, сохраняете версии и можете откатиться. Инструменты иллюстратора тоже доступны.',

  'new.title': 'Новый проект',
  'new.name': 'Название',
  'new.name.hint': 'Можно оставить пустым: возьмём из файла',
  'new.file': 'Файл книги',
  'new.file.formats': 'TXT, EPUB, FB2, DOCX или PDF с текстом',
  'new.file.optional': 'Необязательно: можно начать с пустого проекта или загрузить черновик',
  'new.create': 'Создать проект',
  'new.creating': 'Читаю книгу…',

  'book.chapters': 'Главы',
  'book.untitled': 'Без названия',
  'book.search': 'Поиск по книге',
  'book.search.none': 'Ничего не найдено',
  'book.search.results': 'Найдено: {n}',
  'book.empty.reader': 'В книге нет глав.',
  'book.empty.writer': 'Глав пока нет. Добавьте первую.',
  'book.split.sections':
    'Глав в файле не нашлось, поэтому текст разделён на равные части. Границы можно поправить вручную.',
  'book.view.writer': 'Писатель',
  'book.view.illustrator': 'Иллюстратор',

  'chapter.title.placeholder': 'Название главы',
  'chapter.text.placeholder': 'Текст главы…',
  'chapter.add': 'Добавить главу',
  'chapter.up': 'Выше',
  'chapter.down': 'Ниже',
  'chapter.merge': 'Объединить со следующей',
  'chapter.merge.confirm': 'Присоединить следующую главу к этой? Её название останется строкой в тексте.',
  'chapter.delete': 'Удалить главу',
  'chapter.delete.confirm': 'Удалить главу «{title}» из проекта?',
  'chapter.split.here': 'Начать новую главу отсюда',
  'chapter.split.title': 'Название новой главы',
  'chapter.format.hint': 'Ctrl+B — жирный, Ctrl+I — курсив',

  'versions.title': 'Версии',
  'versions.current': 'Версия {n}',
  'versions.clean': 'Изменений после этой версии нет',
  'versions.dirty': 'Есть незафиксированные изменения',
  'versions.edited': 'изменён текст: {n}',
  'versions.added': 'новых глав: {n}',
  'versions.removed': 'удалено глав: {n}',
  'versions.renamed': 'переименовано: {n}',
  'versions.reordered': 'изменён порядок глав',
  'versions.label': 'Подпись к версии (необязательно)',
  'versions.commit': 'Зафиксировать версию',
  'versions.history': 'История',
  'versions.rollback': 'Откатить',
  'versions.rollback.confirm':
    'Вернуть книгу к версии {n}? Текущее состояние сохранится отдельной версией, ничего не пропадёт.',
  'versions.label.import': 'Импорт',
  'versions.label.start': 'Начало',
  'versions.label.autosave': 'Автосохранение перед откатом',
  'versions.label.rollback': 'Откат к версии {n}',

  'settings.title': 'Настройки',
  'settings.connections': 'Подключения',
  'settings.connections.hint':
    'Подключение — это адрес сервиса и ключ. Подойдёт любой сервис с OpenAI-совместимым API: OpenRouter, OmniRoute и другие.',
  'settings.connections.empty': 'Подключений пока нет.',
  'settings.add': 'Добавить подключение',
  'settings.kind': 'Тип',
  'settings.kind.openai': 'Адрес и ключ (OpenAI-совместимый API)',
  'settings.kind.claude_cli': 'Подписка Claude (через Claude Code на этом компьютере)',
  'settings.kind.claude_cli.hint':
    'Запросы идут через установленный Claude Code и расходуют лимиты вашей подписки, отдельной оплаты нет. Работает только на компьютере, где Claude Code установлен и выполнен вход; на хостинге недоступно. Только текст, без картинок.',
  'settings.kind.claude_cli.missing': 'Claude Code на этом компьютере не найден.',
  'settings.name': 'Название',
  'settings.url': 'Адрес',
  'settings.key': 'API-ключ',
  'settings.key.hint': 'Хранится на сервере в зашифрованном виде и обратно не показывается',
  'settings.key.stored': 'ключ {hint}',
  'settings.key.none': 'без ключа',
  'settings.delete.confirm': 'Удалить подключение «{name}»?',
  'settings.models': 'Модели',
  'settings.models.hint': 'Для текста и для картинок модель выбирается отдельно.',
  'settings.models.text': 'Модель для текста',
  'settings.models.image': 'Модель для картинок',
  'settings.connection': 'Подключение',
  'settings.connection.none': 'Не выбрано',
  'settings.model': 'Модель',
  'settings.model.none': 'Не выбрана',
  'settings.models.loading': 'Загружаю список моделей…',
  'settings.models.count': 'Моделей: {n}',
  'settings.free.only': 'Только бесплатные',
  'settings.free': 'бесплатно',
  'settings.image.unknown':
    'Сервис не сообщает, какие модели умеют рисовать, поэтому показаны все.',
  'settings.test': 'Проверить',
  'settings.testing': 'Проверяю…',
  'settings.test.ok': 'Работает. Ответ: «{reply}». Токены: {input} на вход, {output} на выход.',

  'error.reader_mode_readonly': 'В проекте «Готовая книга» текст не редактируется.',
  'error.unsupported_book': 'Не удалось прочитать файл: формат не поддерживается.',
  'error.empty_book': 'В файле не нашлось текста.',
  'error.book_file_required': 'Для готовой книги нужен файл.',
  'error.file_too_large': 'Файл слишком большой.',
  'error.nothing_to_commit': 'Изменений нет, фиксировать нечего.',
  'error.no_next_chapter': 'Это последняя глава.',
  'error.bad_base_url': 'Адрес должен начинаться с http:// или https://',
  'error.provider_error': 'Сервис ответил ошибкой: {detail}',
  'error.unknown': 'Что-то пошло не так: {detail}',
}

const en: Record<keyof typeof ru, string> = {
  'app.settings': 'Settings',
  'app.projects': 'Projects',
  'app.loading': 'Loading…',
  'app.cancel': 'Cancel',
  'app.delete': 'Delete',
  'app.save': 'Save',
  'app.saved': 'Saved',
  'app.saving': 'Saving…',
  'app.chars': '{n} chars',

  'projects.title': 'Projects',
  'projects.new': 'New project',
  'projects.empty': 'No projects yet. Create the first one: upload a finished book or start writing your own.',
  'projects.chapters': 'chapters: {n}',
  'projects.delete.confirm': 'Delete “{title}” with all its chapters and versions? This cannot be undone.',

  'mode.reader': 'Finished book',
  'mode.writer': 'Writing a book',
  'mode.reader.hint': 'Upload a finished text. It is read-only; you find characters, locations and scenes and prepare them for animation.',
  'mode.writer.hint': 'Write and edit chapters right here, save versions and roll back. Illustrator tools are available too.',

  'new.title': 'New project',
  'new.name': 'Title',
  'new.name.hint': 'Leave empty to take it from the file',
  'new.file': 'Book file',
  'new.file.formats': 'TXT, EPUB, FB2, DOCX or a text PDF',
  'new.file.optional': 'Optional: start with an empty project or upload a draft',
  'new.create': 'Create project',
  'new.creating': 'Reading the book…',

  'book.chapters': 'Chapters',
  'book.untitled': 'Untitled',
  'book.search': 'Search the book',
  'book.search.none': 'Nothing found',
  'book.search.results': 'Found: {n}',
  'book.empty.reader': 'The book has no chapters.',
  'book.empty.writer': 'No chapters yet. Add the first one.',
  'book.split.sections':
    'No chapters were found in the file, so the text was cut into equal parts. You can fix the boundaries by hand.',
  'book.view.writer': 'Writer',
  'book.view.illustrator': 'Illustrator',

  'chapter.title.placeholder': 'Chapter title',
  'chapter.text.placeholder': 'Chapter text…',
  'chapter.add': 'Add chapter',
  'chapter.up': 'Up',
  'chapter.down': 'Down',
  'chapter.merge': 'Merge with next',
  'chapter.merge.confirm': 'Append the next chapter to this one? Its title stays as a line of text.',
  'chapter.delete': 'Delete chapter',
  'chapter.delete.confirm': 'Delete chapter “{title}” from the project?',
  'chapter.split.here': 'Start a new chapter here',
  'chapter.split.title': 'Title of the new chapter',
  'chapter.format.hint': 'Ctrl+B bold, Ctrl+I italic',

  'versions.title': 'Versions',
  'versions.current': 'Version {n}',
  'versions.clean': 'No changes since this version',
  'versions.dirty': 'There are uncommitted changes',
  'versions.edited': 'text changed: {n}',
  'versions.added': 'new chapters: {n}',
  'versions.removed': 'chapters removed: {n}',
  'versions.renamed': 'renamed: {n}',
  'versions.reordered': 'chapter order changed',
  'versions.label': 'Version note (optional)',
  'versions.commit': 'Commit version',
  'versions.history': 'History',
  'versions.rollback': 'Roll back',
  'versions.rollback.confirm':
    'Return the book to version {n}? The current state is saved as its own version, nothing is lost.',
  'versions.label.import': 'Import',
  'versions.label.start': 'Start',
  'versions.label.autosave': 'Autosave before rollback',
  'versions.label.rollback': 'Rollback to version {n}',

  'settings.title': 'Settings',
  'settings.connections': 'Connections',
  'settings.connections.hint':
    'A connection is a service address and a key. Any service with an OpenAI-compatible API works: OpenRouter, OmniRoute and others.',
  'settings.connections.empty': 'No connections yet.',
  'settings.add': 'Add connection',
  'settings.kind': 'Type',
  'settings.kind.openai': 'Address and key (OpenAI-compatible API)',
  'settings.kind.claude_cli': 'Claude subscription (through Claude Code on this computer)',
  'settings.kind.claude_cli.hint':
    'Requests go through the installed Claude Code and use your subscription limits, with no separate billing. Works only on a computer where Claude Code is installed and signed in; not available when hosted. Text only, no images.',
  'settings.kind.claude_cli.missing': 'Claude Code was not found on this computer.',
  'settings.name': 'Name',
  'settings.url': 'Address',
  'settings.key': 'API key',
  'settings.key.hint': 'Stored encrypted on the server and never shown again',
  'settings.key.stored': 'key {hint}',
  'settings.key.none': 'no key',
  'settings.delete.confirm': 'Delete connection “{name}”?',
  'settings.models': 'Models',
  'settings.models.hint': 'Text and images each get their own model.',
  'settings.models.text': 'Text model',
  'settings.models.image': 'Image model',
  'settings.connection': 'Connection',
  'settings.connection.none': 'Not selected',
  'settings.model': 'Model',
  'settings.model.none': 'Not selected',
  'settings.models.loading': 'Loading models…',
  'settings.models.count': 'Models: {n}',
  'settings.free.only': 'Free only',
  'settings.free': 'free',
  'settings.image.unknown': 'The service does not say which models can draw, so all are shown.',
  'settings.test': 'Test',
  'settings.testing': 'Testing…',
  'settings.test.ok': 'Works. Reply: “{reply}”. Tokens: {input} in, {output} out.',

  'error.reader_mode_readonly': 'The text of a “Finished book” project cannot be edited.',
  'error.unsupported_book': 'Could not read the file: the format is not supported.',
  'error.empty_book': 'No text was found in the file.',
  'error.book_file_required': 'A finished book needs a file.',
  'error.file_too_large': 'The file is too large.',
  'error.nothing_to_commit': 'Nothing has changed, nothing to commit.',
  'error.no_next_chapter': 'This is the last chapter.',
  'error.bad_base_url': 'The address must start with http:// or https://',
  'error.provider_error': 'The service returned an error: {detail}',
  'error.unknown': 'Something went wrong: {detail}',
}

export type MessageKey = keyof typeof ru
type Params = Record<string, string | number>
export type Translate = (key: MessageKey, params?: Params) => string

const dictionaries = { ru, en }

const I18nContext = createContext<{ lang: Lang; setLang: (lang: Lang) => void; t: Translate }>(
  null!,
)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() =>
    localStorage.getItem('lang') === 'en' ? 'en' : 'ru',
  )
  const setLang = useCallback((next: Lang) => {
    localStorage.setItem('lang', next)
    document.documentElement.lang = next
    setLangState(next)
  }, [])
  const t = useCallback<Translate>(
    (key, params = {}) =>
      dictionaries[lang][key].replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? '')),
    [lang],
  )
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  return useContext(I18nContext)
}

export function errorText(t: Translate, error: unknown): string {
  if (error instanceof ApiError) {
    const key = `error.${error.code}` as MessageKey
    if (key in ru) return t(key, { detail: error.detail })
    return t('error.unknown', { detail: error.message })
  }
  return t('error.unknown', { detail: error instanceof Error ? error.message : String(error) })
}

/** Version labels written by the server are codes; user labels are shown as typed. */
export function versionLabel(t: Translate, label: string): string {
  if (label === 'import' || label === 'start' || label === 'autosave') {
    return t(`versions.label.${label}`)
  }
  const rollback = label.match(/^rollback:(\d+)$/)
  return rollback ? t('versions.label.rollback', { n: rollback[1] }) : label
}
