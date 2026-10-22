import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { ApiError } from './api'

export type Lang = 'ru' | 'en'

const ru = {
  'app.settings': 'Настройки',
  'app.projects': 'Проекты',
  'app.loading': 'Загрузка…',
  'login.title': 'Вход',
  'login.password': 'Пароль',
  'login.submit': 'Войти',
  'login.logout': 'Выйти',
  'app.cancel': 'Отмена',
  'app.ok': 'ОК',
  'app.delete': 'Удалить',
  'app.close': 'Закрыть',
  'app.save': 'Сохранить',
  'app.saved': 'Сохранено',
  'app.saving': 'Сохраняю…',
  'app.unsaved': 'Не сохранено',
  'app.chars': '{n} зн.',

  'projects.title': 'Проекты',
  'projects.new': 'Новый проект',
  'projects.empty':
    'Проектов пока нет. Создайте первый: загрузите готовую книгу или начните писать свою.',
  'projects.chapters': 'глав: {n}',
  'projects.delete.confirm':
    'Удалить проект «{title}» со всеми главами и версиями? Отменить это нельзя.',

  'mode.reader': 'Готовая книга',
  'mode.writer': 'Пишу книгу',
  'mode.reader.hint':
    'Загружаете готовый текст. Он только читается; вы находите персонажей, локации и сцены и готовите их к оживлению.',
  'mode.writer.hint':
    'Пишете и правите главы прямо здесь, сохраняете версии и можете откатиться. Инструменты иллюстратора тоже доступны.',

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
  'chapter.merge.confirm':
    'Присоединить следующую главу к этой? Её название останется строкой в тексте.',
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

  'tabs.book': 'Главы',
  'nav.chapters': 'Главы',
  'nav.characters': 'Персонажи',
  'nav.locations': 'Локации',
  'nav.scenes': 'Сцены',
  'nav.add.characters': 'Добавить персонажа вручную',
  'nav.add.locations': 'Добавить локацию вручную',
  'nav.find.characters': 'Выгрузить персонажей из книги',
  'nav.find.locations': 'Выгрузить локации из книги',
  'tabs.character': 'Персонажи',
  'tabs.location': 'Локации',
  'tabs.usage': 'Расход',

  'entities.find.character': 'Найти персонажей',
  'entities.find.location': 'Найти локации',
  'entities.search': 'Поиск',
  'entities.search.hint.character': 'ИИ прочитает выбранные главы и найдёт персонажей',
  'entities.search.hint.location': 'ИИ прочитает выбранные главы и найдёт локации',
  'entities.empty.character':
    'Персонажи ещё не найдены. Поиск запускается только по кнопке: сервис читает выбранные главы и собирает карточки с цитатами.',
  'entities.empty.location':
    'Локации ещё не найдены. Поиск запускается только по кнопке: сервис читает выбранные главы и собирает карточки с цитатами.',
  'entities.select': 'Выберите карточку слева.',
  'entities.aliases': 'Также',
  'entities.permanent': 'Постоянное',
  'entities.permanent.none': 'В прочитанных главах постоянных черт не описано.',
  'entities.timeline': 'По главам',
  'entities.present': 'Участвует, новых деталей нет',
  'entities.stale': 'устарело',
  'entities.stale.hint':
    'Текст главы изменился после чтения. Запустите поиск по этой главе заново.',
  'entities.count': 'глав: {chapters} · фактов: {facts}',
  'entities.refresh': 'Текст изменился в главах: {n}. Карточки по ним устарели.',
  'entities.refresh.button': 'Обновить устаревшее',
  'entities.source': 'Открыть в тексте',
  'entities.merge': 'Объединить с…',
  'entities.merge.confirm':
    'Объединить «{other}» с «{name}»? Все факты перейдут в карточку «{name}», а «{other}» станет её другим именем.',
  'entities.split': 'Отделить в свою карточку',
  'entities.split.confirm':
    'Сделать «{alias}» отдельной карточкой? Факты из глав, где книга называет его этим именем, перейдут в неё.',

  'run.title': 'Какие главы читать',
  'run.all': 'Все',
  'run.none': 'Ни одной',
  'run.estimate': 'Оценка расхода',
  'run.estimate.loading': 'Считаю…',
  'run.estimate.body':
    'Запросов: {requests}. Примерно {input} токенов на вход и {output} на выход.',
  'run.estimate.cached': 'Уже прочитано без изменений (бесплатно): {n}.',
  'run.estimate.free': 'Все выбранные главы уже прочитаны, запросов к модели не будет.',
  'run.estimate.note': 'Оценка грубая: точное число зависит от модели.',
  'run.start': 'Запустить',
  'run.progress': 'Читаю главы: {done} из {total}',
  'run.cancel': 'Остановить',
  'run.cancelling': 'Останавливаю после текущей главы…',
  'run.failed':
    'Поиск остановился на главе {done} из {total}: {error}. Прочитанное сохранено, повторный запуск продолжит с этого места.',
  'run.cancelled': 'Поиск остановлен на главе {done} из {total}. Прочитанное сохранено.',
  'run.interrupted': 'сервер был перезапущен',

  'usage.title': 'Расход токенов',
  'usage.empty': 'Запросов к моделям по этому проекту ещё не было.',
  'usage.operation': 'Операция',
  'usage.model': 'Модель',
  'usage.calls': 'Запросов',
  'usage.input': 'На вход',
  'usage.output': 'На выход',
  'usage.total': 'Всего',
  'usage.op.find_characters': 'Поиск персонажей',
  'usage.op.merge_characters': 'Сведение дублей персонажей',
  'usage.op.find_locations': 'Поиск локаций',
  'usage.op.merge_locations': 'Сведение дублей локаций',
  'usage.op.chat': 'Чат по книге',
  'usage.op.suggest_plot': 'Варианты развития событий',
  'usage.op.image_prompt': 'Промпт для картинки',
  'usage.op.image': 'Картинка',
  'usage.op.split_scenes': 'Разбивка на сцены',
  'usage.op.video_prompt': 'Промпт для видео',
  'usage.op.refine_prompt': 'Правка промпта',

  'chat.title': 'Чат по книге',
  'chat.hint':
    'Спросите о книге: как выглядит персонаж, что он собирался сделать, в какой главе что случилось. Ответ строится только по тексту и ссылается на место в книге. Первый вопрос дольше обычного: готовится поиск по книге.',
  'chat.placeholder': 'Вопрос по книге…',
  'chat.send': 'Спросить',
  'chat.waiting': 'Ищу в книге и отвечаю',
  'chat.status.index': 'Листаю книгу',
  'chat.status.search': 'Ищу в книге: «{detail}»',
  'chat.status.read': 'Читаю: «{detail}»',
  'chat.status.think': 'Обдумываю прочитанное',
  'chat.status.seconds': '{n} с',
  'chat.suggest': 'Предложить развитие событий',
  'chat.suggest.question': 'Предложи три варианта, как может продолжиться эта глава.',
  'chat.suggest.empty': 'В открытой главе пока нет текста, продолжать нечего.',
  'chat.clear': 'Очистить',
  'chat.clear.confirm': 'Удалить всю переписку по этому проекту?',
  'chat.empty_book': 'В книге пока нет текста, искать негде.',
  'side.chat': 'Чат',
  'side.versions': 'Версии',

  'tabs.style': 'Стиль',
  'style.title': 'Стиль проекта',
  'style.hint':
    'Один стиль на все картинки проекта, чтобы персонажи и места выглядели как из одного фильма. Он добавляется в каждый промпт.',
  'style.preset.cinematic': 'Кинореализм',
  'style.preset.dark_fantasy': 'Тёмное фэнтези',
  'style.preset.anime': 'Аниме',
  'style.preset.illustration': 'Книжная иллюстрация',
  'style.custom': 'Свой стиль',
  'style.custom.placeholder': 'Опишите стиль, лучше по-английски: его читает нейросеть',
  'style.custom.use': 'Использовать этот стиль',
  'style.change.confirm':
    'Сменить стиль проекта? Картинки, сделанные в прежнем стиле, останутся, но перестанут предлагаться как референсы: их нужно будет создать заново.',

  'gallery.title': 'Референсы',
  'gallery.general': 'Общие референсы проекта',
  'gallery.empty': 'Картинок пока нет. Загрузите свои или сгенерируйте.',
  'gallery.general.empty':
    'Сюда можно сложить картинки, которые задают настроение и стиль всей книги и не относятся к одному персонажу.',
  'gallery.upload': 'Загрузить картинки',
  'gallery.uploading': 'Загружаю…',
  'gallery.main': 'основная',
  'gallery.make_main': 'Сделать базовой',
  'gallery.unmake_main': 'Убрать из базовых',
  'gallery.angle.none': 'ракурс не указан',
  'angle.face_front': 'лицо анфас',
  'angle.full_front': 'рост спереди',
  'angle.face_profile': 'лицо в профиль',
  'angle.face_three_quarter': 'лицо 3/4',
  'angle.full_side': 'рост сбоку',
  'angle.full_back': 'рост сзади',
  'gallery.main.hint':
    'Базовые картинки (★) задают лицо и фигуру: лицо анфас, 3/4 и в профиль, рост спереди, сбоку, сзади. От них рисуются все новые картинки, а в сцену сервис сам берёт лучшее лицо и лучший рост. Остальные — картинки по контексту, например «в кольчуге»; их можно привязать к главе.',
  'gallery.other_style': 'другой стиль',
  'gallery.other_style.hint':
    'Сделана в другом стиле проекта и как референс сейчас не предлагается.',
  'gallery.look.placeholder': 'Облик: например, «в кольчуге»',
  'gallery.chapter.none': 'Без главы',
  'gallery.uploaded': 'Загружена с компьютера',
  'generate.size': 'Размер картинки',
  'generate.size.auto': 'Размер: как у модели',
  'generate.size.1:1': 'Квадрат 1:1 · 1024×1024',
  'generate.size.2:3': 'Портрет 2:3 · 1024×1536',
  'generate.size.3:2': 'Пейзаж 3:2 · 1536×1024',
  'generate.size.9:16': 'Высокий 9:16 · 1024×1792',
  'generate.size.16:9': 'Широкий 16:9 · 1792×1024',
  'gallery.settings': 'Настройки картинки',
  'gallery.apply': 'Применить',
  'gallery.add': 'Добавить',
  'gallery.add.title': 'Новая картинка',
  'gallery.mode.base': 'Базовая',
  'gallery.mode.context': 'По контексту',
  'gallery.mode.context.locked': 'Сначала нужна хотя бы одна базовая картинка: от неё берутся лицо и фигура.',
  'gallery.upload.file': 'Загрузить из файла',
  'gallery.angle': 'Ракурс',
  'gallery.look': 'Облик',
  'gallery.chapter': 'Глава',
  'gallery.delete.confirm': 'Удалить эту картинку? Файл будет стёрт.',

  'generate.title': 'Сгенерировать',
  'generate.slot': 'Здесь появится картинка',
  'generate.angle.auto': 'Ракурс: выберет сервис',
  'generate.prompt.label': 'Промпт',
  'generate.prompt.placeholder': 'Нажмите «Собрать промпт» или напишите свой.',
  'generate.made': 'Картинка сохранена в референсах.',
  'generate.hint.main':
    'Базовая картинка показывает лицо или фигуру с одного ракурса. Первая рисуется с нуля по постоянным чертам карточки или от загруженного фото, следующие — от уже готовых базовых, чтобы лицо совпадало. Промпт можно поправить.',
  'generate.hint.base_set':
    'Набор ракурсов по одному промпту с описанием внешности. Ракурс к каждой картинке добавится сам. Первая картинка станет референсом для остальных, чтобы лицо совпадало; загруженное фото — тоже.',
  'generate.hint.look':
    'Рисуется от базовых картинок. Укажите, что это за облик и к какой главе он относится: в промпт попадут детали из этой главы.',
  'generate.views': 'Ракурсы',
  'generate.set': 'Сгенерировать набор · {n}',
  'generate.set.progress': 'Рисую {done} из {total}: {view}…',
  'generate.set.done': 'Готово: {n} в референсах.',
  'generate.prompt': 'Собрать промпт',
  'generate.prompt.busy': 'Собираю…',
  'generate.image': 'Сгенерировать',
  'generate.image.busy': 'Рисую…',
  'generate.copy': 'Скопировать промпт',
  'generate.no_style': 'Стиль проекта не выбран: промпт будет без стиля, а рисовать нельзя.',
  'entities.add.prompt': 'Имя, как в книге:',

  'tabs.scenes': 'Сцены',
  'scenes.empty':
    'Сцен пока нет. Откройте главу на вкладке «Книга»: там можно разбить её на сцены или выделить мышью нужный кусок текста.',
  'scenes.select': 'Выберите сцену слева.',
  'scenes.vivid': 'Яркая сцена',
  'scenes.split': 'Разбить на сцены',
  'scenes.split.busy': 'Делю главу на сцены…',
  'scenes.split.confirm':
    'Разбить главу на сцены? Примерно {input} токенов на вход и {output} на выход.',
  'scenes.split.replace':
    ' Прежняя автоматическая разбивка этой главы ({n}) будет заменена; сцены, отмеченные вручную, останутся.',
  'scenes.mark': 'Сделать сценой: абзацы {from}–{to}',
  'scene.delete': 'Удалить сцену',
  'scene.delete.confirm': 'Удалить эту сцену вместе с её промптом? Кадры останутся.',
  'scene.stale': 'Текст главы изменился',
  'scene.stale.hint':
    'Текст главы изменился после создания сцены, её границы могли сместиться. Создайте сцену заново.',
  'scene.text': 'Текст сцены',
  'scene.references': 'Референсы',
  'scene.references.none':
    'У участников сцены нет картинок в стиле проекта. Загрузите или сгенерируйте их в карточках, и они подставятся сюда сами.',
  'scene.references.no_style':
    'Стиль проекта не выбран, поэтому референсы не подбираются. Выберите его на вкладке «Стиль».',
  'scene.look': 'облик',
  'scene.prompt': 'Промпт для видео',
  'scene.note.placeholder': 'Пожелания к сцене (необязательно): что показать, откуда камера',
  'scene.build': 'Собрать промпт для видео',
  'scene.rebuild': 'Собрать заново',
  'scene.build.busy': 'Собираю…',
  'scene.refine.placeholder': 'Что изменить: «камера сначала на замок, потом наезд»',
  'scene.refine': 'Изменить',
  'scene.refine.busy': 'Меняю…',
  'scene.copy': 'Скопировать промпт',
  'scene.copied': 'Скопировано',
  'scene.archive': 'Скачать архив',
  'scene.frame': 'Сгенерировать кадр',
  'scene.frames': 'Стартовые кадры',
  'scene.frame.latest': 'последний, идёт в архив',

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
  'error.claude_cli_missing': 'Claude Code на этом компьютере не найден.',
  'error.provider_error': 'Сервис ответил ошибкой: {detail}',
  'error.text_model_not_configured':
    'Не выбрана модель для текста. Откройте Настройки и выберите подключение и модель.',
  'error.analysis_already_running': 'По этому проекту уже идёт поиск. Дождитесь его окончания.',
  'error.no_chapters_selected': 'Не выбрано ни одной главы.',
  'error.chapter_not_found': 'Такой главы больше нет.',
  'error.project_not_found': 'Такого проекта нет.',
  'error.entity_not_found': 'Такой карточки больше нет.',
  'error.version_not_found': 'Такой версии нет.',
  'error.connection_not_found': 'Такого подключения больше нет.',
  'error.title_too_long': 'Название слишком длинное (до 300 знаков).',
  'error.key_unreadable':
    'Сохранённый ключ не удалось расшифровать. Удалите подключение и добавьте его заново.',
  'error.bad_model_output':
    'Модель ответила не в том виде, который ожидался. Попробуйте ещё раз или выберите другую модель.',
  'error.image_model_not_configured':
    'Не выбрана модель для картинок. Откройте Настройки, добавьте подключение с ключом и выберите модель. Промпт можно скопировать и нарисовать в другом сервисе, а результат загрузить сюда.',
  'error.style_not_chosen': 'Сначала выберите стиль проекта на вкладке «Стиль».',
  'error.not_an_image': 'Это не картинка. Подходят PNG, JPEG и WebP.',
  'error.style_text_required': 'Опишите свой стиль.',
  'error.image_not_found': 'Такой картинки больше нет.',
  'error.no_prompt_yet': 'Сначала соберите промпт для видео.',
  'error.scene_not_found': 'Такой сцены больше нет.',
  'error.empty_chapter': 'В главе нет текста.',
  'error.wrong_password': 'Неверный пароль.',
  'error.too_many_attempts': 'Слишком много неверных попыток. Подождите несколько минут.',
  'error.login_required': 'Нужно войти заново.',
  'error.unknown': 'Что-то пошло не так: {detail}',
}

const en: Record<keyof typeof ru, string> = {
  'app.settings': 'Settings',
  'app.projects': 'Projects',
  'app.loading': 'Loading…',
  'login.title': 'Sign in',
  'login.password': 'Password',
  'login.submit': 'Sign in',
  'login.logout': 'Sign out',
  'app.cancel': 'Cancel',
  'app.ok': 'OK',
  'app.delete': 'Delete',
  'app.close': 'Close',
  'app.save': 'Save',
  'app.saved': 'Saved',
  'app.saving': 'Saving…',
  'app.unsaved': 'Not saved',
  'app.chars': '{n} chars',

  'projects.title': 'Projects',
  'projects.new': 'New project',
  'projects.empty':
    'No projects yet. Create the first one: upload a finished book or start writing your own.',
  'projects.chapters': 'chapters: {n}',
  'projects.delete.confirm':
    'Delete “{title}” with all its chapters and versions? This cannot be undone.',

  'mode.reader': 'Finished book',
  'mode.writer': 'Writing a book',
  'mode.reader.hint':
    'Upload a finished text. It is read-only; you find characters, locations and scenes and prepare them for animation.',
  'mode.writer.hint':
    'Write and edit chapters right here, save versions and roll back. Illustrator tools are available too.',

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
  'chapter.merge.confirm':
    'Append the next chapter to this one? Its title stays as a line of text.',
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

  'tabs.book': 'Chapters',
  'nav.chapters': 'Chapters',
  'nav.characters': 'Characters',
  'nav.locations': 'Locations',
  'nav.scenes': 'Scenes',
  'nav.add.characters': 'Add a character by hand',
  'nav.add.locations': 'Add a location by hand',
  'nav.find.characters': 'Extract characters from the book',
  'nav.find.locations': 'Extract locations from the book',
  'tabs.character': 'Characters',
  'tabs.location': 'Locations',
  'tabs.usage': 'Usage',

  'entities.find.character': 'Find characters',
  'entities.find.location': 'Find locations',
  'entities.search': 'Search',
  'entities.search.hint.character': 'AI reads the chosen chapters and finds the characters',
  'entities.search.hint.location': 'AI reads the chosen chapters and finds the locations',
  'entities.empty.character':
    'No characters yet. The search runs only when you start it: the app reads the chapters you pick and builds cards with quotes.',
  'entities.empty.location':
    'No locations yet. The search runs only when you start it: the app reads the chapters you pick and builds cards with quotes.',
  'entities.select': 'Pick a card on the left.',
  'entities.aliases': 'Also',
  'entities.permanent': 'Permanent',
  'entities.permanent.none': 'The chapters read so far describe no permanent traits.',
  'entities.timeline': 'By chapter',
  'entities.present': 'Takes part, no new details',
  'entities.stale': 'stale',
  'entities.stale.hint':
    'The chapter text changed after it was read. Run the search for this chapter again.',
  'entities.count': 'chapters: {chapters} · facts: {facts}',
  'entities.refresh': 'The text changed in {n} chapter(s). Their cards are stale.',
  'entities.refresh.button': 'Refresh what is stale',
  'entities.source': 'Open in the text',
  'entities.merge': 'Merge with…',
  'entities.merge.confirm':
    'Merge “{other}” into “{name}”? All facts move to the “{name}” card and “{other}” becomes its other name.',
  'entities.split': 'Split into its own card',
  'entities.split.confirm':
    'Make “{alias}” a separate card? Facts from chapters where the book uses that name move to it.',

  'run.title': 'Chapters to read',
  'run.all': 'All',
  'run.none': 'None',
  'run.estimate': 'Cost estimate',
  'run.estimate.loading': 'Calculating…',
  'run.estimate.body': 'Requests: {requests}. About {input} tokens in and {output} out.',
  'run.estimate.cached': 'Already read and unchanged (free): {n}.',
  'run.estimate.free': 'All selected chapters are already read; no model requests will be made.',
  'run.estimate.note': 'A rough estimate: the exact number depends on the model.',
  'run.start': 'Start',
  'run.progress': 'Reading chapters: {done} of {total}',
  'run.cancel': 'Stop',
  'run.cancelling': 'Stopping after the current chapter…',
  'run.failed':
    'The search stopped at chapter {done} of {total}: {error}. What was read is saved; starting again continues from there.',
  'run.cancelled': 'The search was stopped at chapter {done} of {total}. What was read is saved.',
  'run.interrupted': 'the server was restarted',

  'usage.title': 'Token usage',
  'usage.empty': 'No model requests for this project yet.',
  'usage.operation': 'Operation',
  'usage.model': 'Model',
  'usage.calls': 'Requests',
  'usage.input': 'In',
  'usage.output': 'Out',
  'usage.total': 'Total',
  'usage.op.find_characters': 'Finding characters',
  'usage.op.merge_characters': 'Merging duplicate characters',
  'usage.op.find_locations': 'Finding locations',
  'usage.op.merge_locations': 'Merging duplicate locations',
  'usage.op.chat': 'Chat about the book',
  'usage.op.suggest_plot': 'Plot suggestions',
  'usage.op.image_prompt': 'Image prompt',
  'usage.op.image': 'Picture',
  'usage.op.split_scenes': 'Splitting into scenes',
  'usage.op.video_prompt': 'Video prompt',
  'usage.op.refine_prompt': 'Prompt change',

  'chat.title': 'Chat about the book',
  'chat.hint':
    'Ask about the book: what a character looks like, what they meant to do, in which chapter something happened. Answers come only from the text and link to the place in the book. The first question takes longer: search over the book is being prepared.',
  'chat.placeholder': 'A question about the book…',
  'chat.send': 'Ask',
  'chat.waiting': 'Searching the book and answering',
  'chat.status.index': 'Leafing through the book',
  'chat.status.search': 'Searching the book: “{detail}”',
  'chat.status.read': 'Reading “{detail}”',
  'chat.status.think': 'Thinking over what I have read',
  'chat.status.seconds': '{n} s',
  'chat.suggest': 'Suggest what happens next',
  'chat.suggest.question': 'Suggest three ways this chapter could go on.',
  'chat.suggest.empty': 'The open chapter has no text yet, so there is nothing to continue.',
  'chat.clear': 'Clear',
  'chat.clear.confirm': 'Delete the whole conversation for this project?',
  'chat.empty_book': 'The book has no text yet, so there is nothing to search.',
  'side.chat': 'Chat',
  'side.versions': 'Versions',

  'tabs.style': 'Style',
  'style.title': 'Project style',
  'style.hint':
    'One style for every picture in the project, so characters and places look like they are from the same film. It is added to every prompt.',
  'style.preset.cinematic': 'Cinematic realism',
  'style.preset.dark_fantasy': 'Dark fantasy',
  'style.preset.anime': 'Anime',
  'style.preset.illustration': 'Book illustration',
  'style.custom': 'Your own style',
  'style.custom.placeholder': 'Describe the style, preferably in English: a model reads it',
  'style.custom.use': 'Use this style',
  'style.change.confirm':
    'Change the project style? Pictures made in the previous style stay, but are no longer offered as references: they will have to be made again.',

  'gallery.title': 'References',
  'gallery.general': 'General project references',
  'gallery.empty': 'No pictures yet. Upload your own or generate one.',
  'gallery.general.empty':
    'Pictures that set the mood and style of the whole book and belong to no single character go here.',
  'gallery.upload': 'Upload pictures',
  'gallery.uploading': 'Uploading…',
  'gallery.main': 'main',
  'gallery.make_main': 'Make base',
  'gallery.unmake_main': 'Remove from base',
  'gallery.angle.none': 'no view set',
  'angle.face_front': 'face, front',
  'angle.full_front': 'full length, front',
  'angle.face_profile': 'face, profile',
  'angle.face_three_quarter': 'face, three-quarter',
  'angle.full_side': 'full length, side',
  'angle.full_back': 'full length, back',
  'gallery.main.hint':
    'Base pictures (★) define the face and build: face from the front, three-quarter and in profile, full length from the front, side and back. Every new picture is drawn from them, and a scene gets the best face and the best full-length view. The rest are pictures in context, for example “in chain mail”; they can be tied to a chapter.',
  'gallery.other_style': 'other style',
  'gallery.other_style.hint':
    'Made in a different project style and not offered as a reference now.',
  'gallery.look.placeholder': 'Look: for example, “in chain mail”',
  'gallery.chapter.none': 'No chapter',
  'gallery.uploaded': 'Uploaded from the computer',
  'generate.size': 'Picture size',
  'generate.size.auto': 'Size: model default',
  'generate.size.1:1': 'Square 1:1 · 1024×1024',
  'generate.size.2:3': 'Portrait 2:3 · 1024×1536',
  'generate.size.3:2': 'Landscape 3:2 · 1536×1024',
  'generate.size.9:16': 'Tall 9:16 · 1024×1792',
  'generate.size.16:9': 'Wide 16:9 · 1792×1024',
  'gallery.settings': 'Picture settings',
  'gallery.apply': 'Apply',
  'gallery.add': 'Add',
  'gallery.add.title': 'New picture',
  'gallery.mode.base': 'Base',
  'gallery.mode.context': 'In context',
  'gallery.mode.context.locked': 'A base picture is needed first: the face and build are taken from it.',
  'gallery.upload.file': 'Upload from a file',
  'gallery.angle': 'View',
  'gallery.look': 'Look',
  'gallery.chapter': 'Chapter',
  'gallery.delete.confirm': 'Delete this picture? The file will be erased.',

  'generate.title': 'Generate',
  'generate.slot': 'The picture appears here',
  'generate.angle.auto': 'View: the service picks',
  'generate.prompt.label': 'Prompt',
  'generate.prompt.placeholder': 'Press “Build prompt” or write your own.',
  'generate.made': 'The picture is saved to the references.',
  'generate.hint.main':
    'A base picture shows the face or the figure from one view. The first is drawn from scratch from the card’s permanent traits or from an uploaded photo, the next ones from the base pictures already there, so the face matches. The prompt can be edited.',
  'generate.hint.base_set':
    'A set of views from one prompt describing the appearance. Each picture gets its view added. The first picture becomes the reference for the rest, so the face matches; an uploaded photo does too.',
  'generate.hint.look':
    'Drawn from the base pictures. Say what look it is and which chapter it belongs to: details from that chapter go into the prompt.',
  'generate.views': 'Views',
  'generate.set': 'Generate the set · {n}',
  'generate.set.progress': 'Drawing {done} of {total}: {view}…',
  'generate.set.done': 'Done: {n} added to the references.',
  'generate.prompt': 'Build prompt',
  'generate.prompt.busy': 'Building…',
  'generate.image': 'Generate',
  'generate.image.busy': 'Drawing…',
  'generate.copy': 'Copy prompt',
  'generate.no_style':
    'No project style is chosen: the prompt will have no style, and drawing is disabled.',
  'entities.add.prompt': 'Name, as in the book:',

  'tabs.scenes': 'Scenes',
  'scenes.empty':
    'No scenes yet. Open a chapter on the Book tab: split it into scenes there, or select the stretch of text you want.',
  'scenes.select': 'Pick a scene on the left.',
  'scenes.vivid': 'A vivid scene',
  'scenes.split': 'Split into scenes',
  'scenes.split.busy': 'Splitting the chapter…',
  'scenes.split.confirm':
    'Split the chapter into scenes? About {input} tokens in and {output} out.',
  'scenes.split.replace':
    ' The earlier automatic split of this chapter ({n}) will be replaced; scenes marked by hand stay.',
  'scenes.mark': 'Make a scene: paragraphs {from}–{to}',
  'scene.delete': 'Delete scene',
  'scene.delete.confirm': 'Delete this scene and its prompt? Frames stay.',
  'scene.stale': 'The chapter text has changed',
  'scene.stale.hint':
    'The chapter text changed after the scene was made, so its boundaries may have moved. Make the scene again.',
  'scene.text': 'Scene text',
  'scene.references': 'References',
  'scene.references.none':
    'Nobody in this scene has pictures in the project style. Upload or generate them on the cards and they will appear here.',
  'scene.references.no_style':
    'No project style is chosen, so references are not picked. Choose one on the Style tab.',
  'scene.look': 'look',
  'scene.prompt': 'Video prompt',
  'scene.note.placeholder': 'Wishes for the scene (optional): what to show, where the camera is',
  'scene.build': 'Build the video prompt',
  'scene.rebuild': 'Build again',
  'scene.build.busy': 'Building…',
  'scene.refine.placeholder': 'What to change: “camera on the castle first, then push in”',
  'scene.refine': 'Change',
  'scene.refine.busy': 'Changing…',
  'scene.copy': 'Copy prompt',
  'scene.copied': 'Copied',
  'scene.archive': 'Download archive',
  'scene.frame': 'Generate frame',
  'scene.frames': 'First frames',
  'scene.frame.latest': 'latest, goes into the archive',

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
  'error.claude_cli_missing': 'Claude Code was not found on this computer.',
  'error.provider_error': 'The service returned an error: {detail}',
  'error.text_model_not_configured':
    'No text model is selected. Open Settings and choose a connection and a model.',
  'error.analysis_already_running':
    'A search is already running for this project. Wait for it to finish.',
  'error.no_chapters_selected': 'No chapters are selected.',
  'error.chapter_not_found': 'This chapter no longer exists.',
  'error.project_not_found': 'This project does not exist.',
  'error.entity_not_found': 'This card no longer exists.',
  'error.version_not_found': 'This version does not exist.',
  'error.connection_not_found': 'This connection no longer exists.',
  'error.title_too_long': 'The title is too long (up to 300 characters).',
  'error.key_unreadable':
    'The stored key could not be decrypted. Delete the connection and add it again.',
  'error.bad_model_output':
    'The model replied in an unexpected form. Try again or choose another model.',
  'error.image_model_not_configured':
    'No image model is selected. Open Settings, add a connection with a key and choose a model. You can copy the prompt, draw it in another service and upload the result here.',
  'error.style_not_chosen': 'Choose the project style on the Style tab first.',
  'error.not_an_image': 'This is not a picture. PNG, JPEG and WebP are accepted.',
  'error.style_text_required': 'Describe your style.',
  'error.image_not_found': 'This picture no longer exists.',
  'error.no_prompt_yet': 'Build the video prompt first.',
  'error.scene_not_found': 'This scene no longer exists.',
  'error.empty_chapter': 'The chapter has no text.',
  'error.wrong_password': 'Wrong password.',
  'error.too_many_attempts': 'Too many wrong attempts. Wait a few minutes.',
  'error.login_required': 'Please sign in again.',
  'error.unknown': 'Something went wrong: {detail}',
}

export type MessageKey = keyof typeof ru
type Params = Record<string, string | number>
export type Translate = (key: MessageKey, params?: Params) => string

const dictionaries = { ru, en }

const I18nContext = createContext<{
  lang: Lang
  setLang: (lang: Lang) => void
  t: Translate
  /** Whether a key built at runtime (an operation code, an error code) has a translation. */
  has: (key: string) => key is MessageKey
}>(null!)

const hasMessage = (key: string): key is MessageKey => key in ru

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
  const value = useMemo(() => ({ lang, setLang, t, has: hasMessage }), [lang, setLang, t])
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
