import logging
import shutil
import json
import os
import asyncio
import datetime
import keyboard as kb
from redminelib import Redmine
from redminelib.exceptions import AuthError, ImpersonateError, ResourceNotFoundError, ValidationError
from requests.exceptions import ConnectionError
from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.types import message
from aiogram.utils import executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils.exceptions import BotBlocked
from filters import IsFwdFilter, IsPrivateFilter


# имя файла с настройками бота
settings_filename = 'settings.json'

# имя файла с токеном бота и администраторами бота
admin_filename = 'admin.json'

# имя файла с группами, куда добавлен бот: идентификатор : наименование группы
groups_filename = 'groups.json'

# имя файла с картинкой для вывода в помощи
help_image = os.path.join('media', 'help.jpg')

SETTINGS = {}   # словарь с настройками бота
ADMIN = {}      # словарь с токеном бота и администраторами бота
GROUPS = {}     # словарь с группами, куда добавлен бот: идентификатор : наименование группы

messages = {}  # словарь с типовыми сообщениями: тип сообщения : содержание сообщения

tmpdir = 'tmp'  # дирректория для хранения прикрепляемых временных файлов
'''
Словарь с закешированными командами /new /update: используется для возможности создания/обновления задач при пересылке сообщения непосредственно боту.
key = id пльзователя, value = [время, команда, аргументы команды, автоочистка]
При пересылке сообщения боту указывается команда - она поступает первым сообщением боту и кешируется. Вторым сообщением приходит пересылаемое сообщение,
при обработке которого команда извлекается из кэша. Для каждого пользователя кэшируется только одна команда. Если за время command_live_time команда не извлечена
обработчиком сообщения с данными, то счиатеся, что сообщение с данными не поступило.
'''
commands_cache = {}
# Период в сек. для запуска процедуры очистки кэша команд
clean_time = 6

# Время жизни в сек. для команды в кэше.
# Если за это время команда не будет извлечана из кэша каким-либо обработчиком сообщения, тогда считаем, что
command_live_time = 5

# region init

# загрузить базовые настройки
try:
    with open(admin_filename, encoding='utf-8') as f:
        ADMIN = json.load(f)
        f.close
except:
    raise Exception


# region aiogram init
bot = Bot(token=ADMIN['TOKEN'])
dp = Dispatcher(bot, loop=asyncio.get_event_loop())

# кастомные фильтры
dp.filters_factory.bind(IsPrivateFilter)
dp.filters_factory.bind(IsFwdFilter)

# логгирование
lg = logging
# DEBUG, INFO, WARNING, ERROR, CRITICAL
lg.basicConfig(filename='bot.log', level=logging.INFO)
# логирование aiogram
log = LoggingMiddleware(lg.__name__)
dp.middleware.setup(log)
# endregion
# endregion

# region general


def init_messages():
    '''Инициирует тексты сообщений'''
    global messages

    messages['start_msg'] = '\
Это бот, который поможет вам взаимодействовать с <a href="' + SETTINGS['RMADRESS'] + '"> Redmine</a>.\n\
На данный момент я могу:\n\
- Отобразить связанынй с чатом проект Redmine в котором будут создаваться задачи \
(для каждого чата может быть задан отдельный проект или использоваться проект по умолчанию)\n\
- Создать в Redmine задачу на основе сообщения из чата. Проект для задачи определяется по настройкам чата.\n\
- Добавить в задачу Redmine коментарий на основе сообщения из чата.\n\
Cписок команд, которые вы можете использовать:'

    messages['help_msg'] = '\
<b>Доступные команды пользователя:</b>\n\
/start - начать работу с ботом\n\
/help - отобразить данную подсказку\n\
/project - отобразить сопоставленный с чатом проект Redmine\n\
/setproject <b>projectname</b> - сопоставить чату проект Redmine <b>projectname</b> вместо проекта по умолчанию. В случае группового чата команда доступна его администратору\n\
\n\
<b><i>Создание и обновление зазач Redmine</i></b>\n\
Данные команды могут быть введены одним из способов:\n\
- в ответ на сообщение с данными* для задачи (бот должен быть добавлен в чат и в контакты пользователя);\n\
- при пересылке боту сообщения с данными* для задачи из любого чата (бот должен быть добавлен в контакты пользователя, наличие бота в исходном чате не обязательно)\n\
\n\
<i>*Сообщение с данными должно содержать текст, файл или картинку. Если сообщение содержит галерею или несколько файлов, то в задачу будет добавлен только один файл, непосредственно в ответ на который или при пересылке которого вводится команда.</i>\n\
\n\
/new <b>заголовок</b> - создать новую задачу Redmine с заголовком <b>заголовок</b> и добавить в него данные сообщения. \
\n\
/update <b>id</b> - обновить задачу Redmine с указанным <b>id</b>, добавив в комментарии данные сообщения.\n\
\n\
<i>В случае, если команда введена из группового чата, ответ поступит в ваш личный чат с ботом</i>\n\
Подробнее: <a href="' + SETTINGS['RMADRESS'] + 'projects/telebot/wiki"> Wiki</a>'

    messages['help_admin_msg'] = '\
<b>Доступные команды администратора бота:</b>\n\
/settings - текущие настройки\n\
/setrmadress <b>adress</b>- установить <b>adress</b> в формате https://adress как адрес сервера Redmine\n\
/setrmtkn <b>token</b> - установить токен Redmine где <b>token</b> - строка с токеном\n\
/adduser <b>id</b> - сопоставить пользователю Telegram пользователя Redmine с указанным <b>id</b>. Команда вводится в ответ на сообщение сопоставляемого пользователя\n\
/deluser <b>id</b> - удалить сопоставление пользователя Telegram с указанным <b>id</b> (пользователь не сможет использовать функционал бота)\n\
/setdefault <b>projectname</b> - установить <b>projectname</b> как проект Redmine по умолчанию для создания задач\n\
/setproject <b>projectname</b> - сопоставить чату  проект Redmine <b>projectname</b> вместо проекта по умолчанию.\n\
/broadcast <b>msg</b> - если команда введена из приватного чата с ботом, то разослать сообщение <b>msg</b> по всем групповым чатам, иначе отправить только в текущий групповой чат\n\
/imp <b>i</b> - выключить (i = 0) или включить (i = 1) имперсонализацию при работе с Redmine. В случае, если включена, бот должен иметь права администратора Redmine\n\
/groups - список групповых чатов, где присутствует бот\n\
\n\
<i>В случае, если команда введена из группового чата, ответ поступит в личный чат с ботом</i>'

    messages[
        'notregisterd_msg'] = f'Похоже, вам не доступен функционал бота. Обратитесь к администратору для настройки прав доступа.'  # @{ADMIN["BOT_ADMINS"][0]}


def load_settings():
    '''Загружает настройки и список групп из json'''
    global SETTINGS
    global GROUPS
    try:
        with open(settings_filename, encoding='utf-8') as f:
            SETTINGS = json.load(f)
            f.close
    except:
        default_settings = {
            'RMADRESS': '',                 # адрес сервера redmine
            'RMTOKEN': '',                  # токен redmine
            # проект по умолчанию, где создаются задачи  список: (Полное имя проекта, краткое имя проекта)
            'DEFAULT_PROJECT': ('', ''),
            # пользователи redmine сопоставленные пользователям . ключ - пользователь Telegram, значение - id пользователя redmine
            'TGUSER_RMUSER': {},
            # проект redmine сопоставленный чату. ключ - чат Telegram (chat_id), значение - список: (Полное имя проекта, краткое имя проекта, Имя чата)
            'CHAT_PROJECT': {},
            # Использовать имперсонализацию (изменять настройку в файле вручную)
            "IMPERSON": 0
        }
        SETTINGS = default_settings

        with open(settings_filename, 'w') as f:
            f.write(json.dumps(SETTINGS))
            f.close

    try:
        with open(groups_filename, encoding='utf-8') as f:
            GROUPS = json.load(f)
            f.close
    except:
        default_groups = {
            'ID': 0,                 # Идентификатор
            'NAME': "",              # Имя
        }
        GROUPS = default_groups

        with open(groups_filename, 'w') as f:
            f.write(json.dumps(GROUPS))
            f.close


async def is_group(message: types.Message):
    '''Прверяет, является ли чат групповым (return True, else False)'''

    return message.chat.type in ("group", "supergroup")


async def is_bot_admin(message: types.message):
    '''Проверяет, является ли бот адимном чата (return True, else False)'''

    member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
    return member.is_chat_admin()


async def is_user_admin(message: types.message):
    '''Проверяет, является ли пользователь, от которого поступило сообщение, адимном чата (return True, else False)'''

    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.is_chat_admin()


async def fwd_and_dell(message: types.Message):
    ''''Проверяет, откуда поступило сообщение. Если из группы - перенаправляет его в личку и удаляет оригинал в группе '''

    forward_ok = False
    # Если сообщение из группового чата, отфорвардить его в личку
    if await is_group(message):
        try:
            await message.forward(message.from_user.id)
            forward_ok = True
        except:
            await message.reply(
                'Выполнение команды прервано! Добавьте бота себе в контакты, чтобы ответы на команды приходили в личные сообщения.')

        # Если бот имеет в чате права администратора - удалить исходное сообщение в групповом чате
        if await is_bot_admin(message):
            await message.bot.delete_message(message.chat.id, message.message_id)

        return forward_ok
    return True


async def display_help(message: types.Message):
    '''Выводит сообщение с информацией о помощи'''

    await message.bot.send_message(message.from_user.id, messages['help_msg'], parse_mode=types.ParseMode.HTML, reply_markup=kb.user_kb)

    if os.path.exists(help_image):
        photo = types.InputFile(help_image)
        await bot.send_photo(chat_id=message.from_user.id, photo=photo)

    if await is_user_bot_admin(message):
        await message.bot.send_message(message.from_user.id, messages['help_admin_msg'], parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)


async def get_rm_project(chat_id: str):
    '''
    Возвращает проект Redmine
    chat_id (str) - идентификатор чата в телеграмм.

    По переданному идентифиактору чата возвращает:
    project (obj) - сопоставленный с идентификатором проект redmine, а если сопоставление не заданно, то глобальный проект по умолчанию,
    информацию о том, является ли данный проект глобальным проектом по умолчанию,
    is_default (bool)- информацию о том, является ли данный проект глобальным проектом по умолчанию,
    status (str) - ОК или Ошибка,
    project_name (str) - короткое имя проекта из настроек
    '''
    project_name = SETTINGS['CHAT_PROJECT'].get(
        chat_id, SETTINGS['DEFAULT_PROJECT'])[1]
    project, status = await get_rm_project_obj(project_name)

    is_default = project_name == SETTINGS['DEFAULT_PROJECT']

    return project, is_default, status, project_name


async def display_project_info(message: types.Message):
    '''Выводит сообщение с информацией о сопоставленном проекте редмайн'''

    project, is_default, status, project_name = await get_rm_project(
        str(message.chat.id))

    chat_name = message.chat.full_name
    kboard = kb.admin_kb if await is_user_bot_admin(message) else kb.user_kb
    if status == 'OK':
        msg = f'Для чата {chat_name}  {"используется проект по умолчанию" if is_default else "используется проект"} <b>{project.name}</b> ({project_name})'
    else:
        msg = f'Для чата {chat_name}  {"используется проект по умолчанию" if is_default else "используется проект"} {project_name}, \
        данные по которому получить не удалось ({status})!'

    await message.bot.send_message(message.from_user.id, msg, parse_mode=types.ParseMode.HTML, reply_markup=kboard)


async def is_user_bot_admin(message: types.Message):
    '''Проверяет, является ли пользователь администратором бота (True|False)'''

    return str(message.from_user.id) in ADMIN['BOT_ADMINS'].keys()


async def is_user_rm_user(message: types.Message):
    '''Проверяет, сопоставлен ли пользователю телеграмм пользователь Redmine (True|False)'''

    return str(message.from_user.id) in SETTINGS['TGUSER_RMUSER'].keys()


async def user_not_admin(message: types.Message):
    ''' Выводит сообщение что пользователь не является администратором бота'''

    await message.bot.send_message(message.from_user.id, 'Вы не можете использовать данную команду!', parse_mode=types.ParseMode.HTML, reply_markup=kb.user_kb)


async def save_settings():
    '''Cохраняет текущие настройки в файл json'''

    try:
        with open(settings_filename, 'w') as f:
            f.write(json.dumps(SETTINGS))
            f.close
            lg.log(20, f"Настройки сохранены")

    except Exception as exception:
        lg.log(40, f"Ошибка сохранения настроек: {exception}")


async def add_group(message: types.message):
    '''
    message (obj) - сообщение из группы
    Добавляет группу из сообщения в настройки и сохраняет текущие настройки групп в файл json
    '''

    global GROUPS
    GROUPS[str(message.chat.id)] = message.chat.full_name
    try:
        with open(groups_filename, 'w') as f:
            f.write(json.dumps(GROUPS))
            f.close
            lg.log(
                20, f"Добавлена группа {message.Chat.full_name} ({message.Chat.id})")
    except Exception as exception:
        lg.log(40, f"Ошибка сохранения групп: {exception}")


async def broadcast(message: types.message, channels: dict, msg_txt: str):
    '''
    Широковещательная рассылка сообщения msg_txt по словарю channels
    message (obj) - входящее сообщение 
    channels (dict) - словарь, ключи которого являются идентифиакторами групп, куда пересылается сообщение
    msg_txt - сообщение к пересылке
    '''
    for k in channels.keys():
        try:
            await message.bot.send_message(int(k), msg_txt, parse_mode=types.ParseMode.HTML)
            await asyncio.sleep(0.5)

        except Exception as exception:
            lg.log(
                40, f"Ошибка отправки широковещательного сообщения в группу {channels[k]} ({k}): {exception}")


async def save_tmp_file(message: types.message, replyed_msg: types.message, msg_tmpdir: str):
    '''
    Сохраняет файл во временную папку. Возвращает путь и имя файла в контейнере, необходимом для загрузки в Redmine
    message (obj) - входящее сообщение 
    replyed_msg (obj) - сообщение, на которое отвечает message (содержит файл)
    msg_tmpdir (str) - временный каталог
    '''

    file_name = ''
    file_path = ''
    if replyed_msg.content_type in ['document']:
        file_info = await bot.get_file(replyed_msg.document.file_id)
        file_name = replyed_msg.document.file_name
        file_path = os.path.join(msg_tmpdir,  file_name)
        await bot.download_file(file_info.file_path, file_path)

    elif replyed_msg.content_type in ['photo']:
        file_info = await bot.get_file(replyed_msg.photo[len(replyed_msg.photo) - 1].file_id)
        file_name = file_info.file_path.split('/')[1]
        file_path = os.path.join(msg_tmpdir,  file_name)
        await bot.download_file(file_info.file_path, file_path)

    if file_path == '':
        uploads = []
    else:
        uploads = [{'path': os.path.join(
            os.getcwd(), file_path), 'filename': file_name}]

    return uploads


async def create_tmp_dir(message: types.message):
    '''
    Cоздает временную дирректорию для хранения файла и возвращает относительный путь к ней
    message (obj) - входящее сообщение 
    '''

    msg_id = str(message.message_id)
    chat_id = str(message.chat.id)

    if not os.path.exists(tmpdir):
        os.mkdir(tmpdir)

    chat_tmpdir = os.path.join(tmpdir, chat_id)
    if not os.path.exists(chat_tmpdir):
        os.mkdir(chat_tmpdir)

    msg_tmpdir = os.path.join(chat_tmpdir, msg_id)
    os.mkdir(msg_tmpdir)

    return msg_tmpdir


async def rm_tmp_dir(tmp_dir: str):
    '''
    Удаляет временную дирректорию
    msg_tmpdir (str) - временный каталог
    '''
    if os.path.exists(tmp_dir) and os.path.isdir(tmp_dir):
        try:
            shutil.rmtree(tmp_dir)
        except Exception as e:
            lg.log(40, f'Failed to delete {tmp_dir}. Reason: {e}')


async def periodic_clean_commands_cache():
    '''С интервалом clean_time очищает кэш команд commands_cache , удаляя старые команды, время жизни которых больше command_live_time.
    Если за время command_live_time команда не извлечена обработчиком сообщения с данными, то счиатеся, 
    что сообщение с данными не поступило
    '''

    global commands_cache
    while True:
        await asyncio.sleep(clean_time)
        time_change = datetime.timedelta(seconds=command_live_time)
        min_cache_time = datetime.datetime.now() - time_change

        to_clean = []

        for key, value in commands_cache.items():
            if value[0] < min_cache_time and value[3]:
                to_clean.append(key)

        for k in to_clean:

            command = 'создана' if commands_cache[k][1] == 'new' else 'обновлена'
            commands_cache.pop(k)
            await bot.send_message(k,
                                   f'Задача Redmine не {command}!\nКоманду необходимо вводить в ответ на сообщение, содержащее данные для создаваемой задачи!',
                                   parse_mode=types.ParseMode.HTML)


# endregion

# region Redmine


async def check_rm_connetction(url='', key=''):
    '''
    Проеряет возможность сосединения с Redmine путем авторизации.
    url (str) - адрес
    key (str) - строка с токеном
    Возвращает Ложь и описание ошибки в случае неудачи или Истина с пустым описанием при успехе
    если url и/или key заданы, то для проверки будут использованы они, иначе из настроек
    '''

    url = url if url != '' else SETTINGS['RMADRESS']
    key = key if key != '' else SETTINGS['RMTOKEN']
    redmine = await get_redmine(url=url, key=key)
    try:
        redmine.auth()
        return True, ''
    except ConnectionError as e:
        return False, 'ConnectionError'
    except AuthError as e:
        return False, 'AuthError'
    except Exception as e:
        return False, 'Exception'


async def get_redmine(url='', key='', userlogin=''):
    '''
    url (str) - адрес
    key (str) - строка с токеном
    userlogin (str) - логин пользователя

    Возвращает объект Redmine.

    Если url и/или key заданы, то будут использованы они, иначе из настроек.
    Если включена имперсонализация в настройках и передан логин - использовать имперсонализацию
    '''
    url = url if url != '' else SETTINGS['RMADRESS']
    key = key if key != '' else SETTINGS['RMTOKEN']
    if SETTINGS['IMPERSON'] and userlogin != '':
        return Redmine(url, key=key, requests={'verify': False}, version='3.4.6', impersonate=userlogin)
    else:
        return Redmine(url, key=key, requests={'verify': False}, version='3.4.6')


async def get_rm_project_obj(project_name: str):
    '''
    Получает проект в Redmine по его имени.
    project_name (str) - идентификатор проекта

    Возвращает: 
    project (obj) - проект-объект, если найден, иначе None
    status (str) - "ОК" или "Exeption"    
    '''
    rm = await get_redmine()

    try:
        project = rm.project.get(project_name)
        status = 'OK'
    except ResourceNotFoundError:
        project = None
        status = 'ResourceNotFoundError'
        lg.log(40, 'Ошибка получения данных проета Redmine: ResourceNotFoundError')
    except ConnectionError:
        project = None
        status = 'ResourceNotFoundError'
        lg.log(40, 'Ошибка получения данных проета Redmine: ConnectionError')
    except ResourceNotFoundError:
        project = None
        status = 'ResourceNotFoundError'
        lg.log(40, 'Ошибка получения данных проета Redmine: AuthError')
    except ImpersonateError:
        issue = None
        status = 'ImpersonateError (ошибка использования указанного пользователя)'
        lg.log(40, 'Ошибка получения данных проета Redmine: ImpersonateError (ошибка использования указанного пользователя)')
    except Exception as e:
        project = None
        status = 'Exception'
        lg.log(40, f'Ошибка получения данных проета Redmine: Exception {e}')

    return project, status


async def get_rm_user_obj(user_id: int):
    '''Получает пользователя в Redmine по его ID.
    user_id (int) - id пользователя
    Возвращает:
    user -  пользователь-объет, если найден, иначе None
    status (str) - "ОК" или "Exeption" 
    '''
    rm = await get_redmine()

    try:
        user = rm.user.get(user_id)
        status = 'OK'
    except ResourceNotFoundError:
        user = None
        status = 'ResourceNotFoundError'
        lg.log(40, 'Ошибка получения данных пользователя Redmine: ResourceNotFoundError')
    except ConnectionError:
        user = None
        status = 'ConnectionError'
        lg.log(40, 'Ошибка получения данных пользователя Redmine: ConnectionError')
    except AuthError:
        user = None
        status = 'ResourceNotFoundError'
        lg.log(40, 'Ошибка получения данных пользователя Redmine: AuthError')
    except ImpersonateError:
        issue = None
        status = 'ImpersonateError (ошибка использования указанного пользователя)'
        lg.log(40, 'Ошибка получения данных пользователя Redmine: ImpersonateError (ошибка использования указанного пользователя)')
    except Exception as e:
        user = None
        status = 'Exception'
        lg.log(
            40, f'Ошибка получения данных пользователя Redmine: Exception {e}')

    return user, status


async def create_issue(project_id: str, subject: str, description: str, assigned_to_id: str, uploads=[]):
    '''Cоздает новую задачу Redmine. 

    project_id (str) - идентификатор проекта
    subject (str) - заголовок задачи
    description (str) - описание задачи
    assigned_to_id (str) - пользователь, которому назначена задача 
    uploads (list) - список вложений

    Возвращает:
    issue - экзепляр задачи, если создана, иначе None
    status (str) - "ОК" или "Exeption" 
    '''
    userlogin = ''
    if SETTINGS['IMPERSON']:
        user, status = await get_rm_user_obj(assigned_to_id)
        if status != 'OK':
            return
        try:
            userlogin = user.login
        except:
            lg.log(
                40, 'Ошибка получения логина пользователя Redmine: CantGetUserLogin (нехватает прав Redmine)')
            return None, 'CantGetUserLogin (нехватает прав Redmine)'

    rm = await get_redmine(userlogin=userlogin)

    try:
        issue = rm.issue.create(project_id=project_id,
                                subject=subject,
                                description=description,
                                uploads=uploads,
                                assigned_to_id=assigned_to_id)
        status = 'OK'
    except ResourceNotFoundError:
        issue = None
        status = 'ResourceNotFoundError'
        lg.log(40, 'Ошибка создания задачи Redmine: ResourceNotFoundError')
    except ConnectionError:
        issue = None
        status = 'ConnectionError'
        lg.log(40, 'Ошибка создания задачи Redmine: ConnectionError')
    except AuthError:
        issue = None
        status = 'AuthError'
        lg.log(40, 'Ошибка создания задачи Redmine: AuthError')
    except ValidationError:
        issue = None
        status = 'ValidationError (недостаточно прав)'
        lg.log(40, 'Ошибка создания задачи Redmine: ValidationError (недостаточно прав)')
    except ImpersonateError:
        issue = None
        status = 'ImpersonateError (ошибка использования указанного пользователя)'
        lg.log(40, 'Ошибка создания задачи Redmine: ImpersonateError (ошибка использования указанного пользователя)')
    except Exception as e:
        issue = None
        status = 'Exception'
        lg.log(40, f'Ошибка создания задачи Redmine: Exception {e}')

    return issue, status


async def update_issue(resource_id: int, assigned_to_id='', notes='', uploads=[]):
    '''
    Обновляет задачу Redmine, добавляя комментарий
    resource_id (int) - идентификатор задачи
    assigned_to_id (str) - пользователь редмайн, от чьего имени комментарий 
    uploads (list) - список вложений

    Возвращает:
    issue - экзепляр задачи, если комментарий добавлен, иначе None
    status (str) - "ОК" или "Exeption"
    '''
    userlogin = ''
    if SETTINGS['IMPERSON']:
        user, status = await get_rm_user_obj(assigned_to_id)
        if status != 'OK':
            return
        userlogin = user.login

    rm = await get_redmine(userlogin=userlogin)

    try:
        issue = rm.issue.update(resource_id=resource_id,
                                notes=notes, uploads=uploads)
        status = 'OK'
    except ResourceNotFoundError:
        issue = None
        status = 'ResourceNotFoundError'
        lg.log(40, 'Ошибка обновления задачи Redmine: ResourceNotFoundError')
    except ConnectionError:
        issue = None
        status = 'ConnectionError'
        lg.log(40, 'Ошибка обновления задачи Redmine: ConnectionError')
    except AuthError:
        issue = None
        status = 'AuthError'
        lg.log(40, 'Ошибка обновления задачи Redmine: AuthError')
    except ImpersonateError:
        issue = None
        status = 'ImpersonateError (ошибка использования указанного пользователя)'
        lg.log(40, 'Ошибка обновления задачи Redmine: ImpersonateError (ошибка использования указанного пользователя)')
    except Exception as e:
        issue = None
        status = 'Exception'
        lg.log(40, f'Ошибка обновления задачи Redmine: Exception {e}')

    return issue, status


# endregion

# region обработчики сообщений-команд


@ dp.message_handler(commands=['start'])
async def process_start_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if not (await is_user_bot_admin(message) or await is_user_rm_user(message)):
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)
        return

    await message.bot.send_message(message.from_user.id, messages['start_msg'], parse_mode=types.ParseMode.HTML)
    await display_help(message)


@ dp.message_handler(commands=['help'])
async def process_help_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if not (await is_user_bot_admin(message) or await is_user_rm_user(message)):
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)
        return

    await display_help(message)


@ dp.message_handler(commands=['project'])
async def process_project_command(message: types.Message):
    await fwd_and_dell(message)

    if not (await is_user_bot_admin(message) or await is_user_rm_user(message)):
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)
        return

    await display_project_info(message)


@ dp.message_handler(commands=['setrmadress'])
async def process_setrmadress_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if await is_user_bot_admin(message):
        global SETTINGS
        # получить переданный адрес и проверить, что он не пустой
        url = message.text.split('/setrmadress', 1)[1].strip()
        if url == '':
            await message.bot.send_message(message.from_user.id, 'Адрес не изменен: не задан адрес Redmine!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        if url[-1] != '/':
            url = url + '/'
        # проверить возможность соединения по переданному адресу
        sucsess, error = await check_rm_connetction(url=url)
        if sucsess or error == 'AuthError':
            # изменить адрес и сохранить настройки
            SETTINGS['RMADRESS'] = url
            await save_settings()
            await message.bot.send_message(message.from_user.id, f'Адрес <a href="{url}">Redmine</a> установлен!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

        elif error == 'ConnectionError':
            await message.bot.send_message(message.from_user.id, 'Адрес не установлен: ошибка соединения с указаным сервером Redmine!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

        elif error == 'Exception':
            await message.bot.send_message(message.from_user.id, 'Адрес не установлен: неизвестная ошибка!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['setrmtkn'])
async def process_setrmtkn_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if await is_user_bot_admin(message):
        global SETTINGS

        if SETTINGS['RMADRESS'] == "":
            await message.bot.send_message(message.from_user.id, 'Токен не изменен: сначала задайте адрес Redmine!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        # получить переданный адрес и проверить, что он не пустой
        key = message.text.split('/setrmtkn', 1)[1].strip()
        if key == '':
            await message.bot.send_message(message.from_user.id, 'Токен не изменен: не задан токен!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        # проверить возможность соединения по переданному токену
        sucsess, error = await check_rm_connetction(key=key)

        if sucsess:
            # изменить адрес и сохранить настройки
            SETTINGS['RMTOKEN'] = key
            await save_settings()
            await message.bot.send_message(message.from_user.id, f'Токен успешно установлен!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

        elif error == 'ConnectionError':
            await message.bot.send_message(message.from_user.id, 'Токен не установлен: ошибка соединения с сервером Redmine!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

        elif error == 'AuthError':
            await message.bot.send_message(message.from_user.id, 'Токен не установлен: неверный токен (ошибка авторизации)!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

        elif error == 'Exception':
            await message.bot.send_message(message.from_user.id, 'Токен не установлен: неизвестная ошибка!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['imp'])
async def process_setimp_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if await is_user_bot_admin(message):
        global SETTINGS

        # получить переданный адрес и проверить, что он не пустой
        par = message.text.split('/imp', 1)[1].strip()
        if par == '':
            await message.bot.send_message(message.from_user.id, 'Не задано значение параметра: должно быть 1 или 0', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        try:
            i = int(par)
        except:
            await message.bot.send_message(message.from_user.id, 'Неверное значение параметра: должно быть 1 или 0!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        if not (i == 1 or i == 0):
            await message.bot.send_message(message.from_user.id, 'Неверное значение параметра: должно быть 1 или 0!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        # изменить адрес и сохранить настройки
        SETTINGS['IMPERSON'] = i
        await save_settings()
        await message.bot.send_message(message.from_user.id, f'Имперсонализация {"включена. Бот должен иметь парава администратора Redmine" if i else "выключена"}!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['setdefault'])
async def process_setdefault_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if await is_user_bot_admin(message):
        global SETTINGS

        if SETTINGS['RMADRESS'] == "":
            await message.bot.send_message(message.from_user.id, 'Проект не изменен: сначала задайте адрес Redmine!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        # получить переданный адрес и проверить, что он не пустой
        prname = message.text.split('/setdefault', 1)[1].strip()
        if prname == '':
            await message.bot.send_message(message.from_user.id, 'Проект не изменен: не задано имя проекта!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        # проверить наличие проекта с указанными именем
        project, status = await get_rm_project_obj(prname)
        if project == None:
            await message.bot.send_message(message.from_user.id, f'Проект не изменен, невозможно получить проект {prname}: {status}!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        # изменить проект и сохранить настройки

        SETTINGS['DEFAULT_PROJECT'] = (str(project), prname)

        await save_settings()
        await message.bot.send_message(message.from_user.id, f'Проект по умолчанию успешно установлен: <a href="{SETTINGS["RMADRESS"]}projects/{prname}">{str(project)}</a>!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['setproject'])
async def process_project_command(message: types.Message):
    kboard = kb.admin_kb if await is_user_bot_admin(message) else kb.user_kb

    if not await fwd_and_dell(message):
        return

    # Проект группового чата может изменять администратор чата, если ему доступен Redmine или администратор бота
    if not await is_group(message) or (await is_user_admin(message) and await is_user_rm_user(message)) or await is_user_bot_admin(message):
        global SETTINGS

        chat_id = message.chat.id
        chat_name = message.chat.full_name

        if SETTINGS['RMADRESS'] == "":
            await message.bot.send_message(message.from_user.id, 'Проект не сопоставлен чату {chat_name}: сначала задайте адрес Redmine!', parse_mode=types.ParseMode.HTML, reply_markup=kboard)
            return

        # получить переданный адрес и проверить, что он не пустой
        prname = message.text.split('/setproject', 1)[1].strip()
        if prname == '':
            await message.bot.send_message(message.from_user.id, 'Проект не сопоставлен чату {chat_name}: не задано имя проекта!', parse_mode=types.ParseMode.HTML, reply_markup=kboard)
            return

        # проверить наличие проекта с указанными именем
        project, status = await get_rm_project_obj(prname)
        if project == None:
            await message.bot.send_message(message.from_user.id, f'Проект не сопоставлен чату {chat_name}, невозможно получить проект {prname}: {status}!', parse_mode=types.ParseMode.HTML, reply_markup=kboard)
            return

        # изменить проект и сохранить настройки
        SETTINGS['CHAT_PROJECT'][str(chat_id)] = (
            str(project), prname, chat_name)
        await save_settings()
        await message.bot.send_message(message.from_user.id, f'Чату {chat_name} успешно сопоставлен проект  <a href="{SETTINGS["RMADRESS"]}projects/{prname}">{str(project)}</a>!', parse_mode=types.ParseMode.HTML, reply_markup=kboard)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['adduser'])
async def process_adduser_command(message: types.Message):

    if not await fwd_and_dell(message):
        return

    if message.reply_to_message == None:
        await message.bot.send_message(message.from_user.id, '<i>Данная команда должна вводится в ответ на сообщение сопоставляемого пользователя</i>', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
        return

    if await is_user_bot_admin(message):
        global SETTINGS

        if SETTINGS['RMADRESS'] == "":
            await message.bot.send_message(message.from_user.id, 'Пользователь не сопоставлен: сначала задайте адрес Redmine!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        user_id = message.reply_to_message.from_user.id
        user_name = message.reply_to_message.from_user.full_name

        # получить переданный id пользователя Redmine и проверить, что он не пустой
        user_id_rm = message.text.split('/adduser', 1)[1].strip()
        if user_id_rm == '':
            await message.bot.send_message(message.from_user.id, 'Пользователь не сопоставлен: не задан ID Redmine!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        # проверить наличие пользователя с указанными id
        user, status = await get_rm_user_obj(user_id_rm)
        if user == None:
            await message.bot.send_message(message.from_user.id, f'Пользователь не сопоставлен: невозможно получить пользователя с id {user_id_rm}: {status}!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
            return

        # изменить пользователя и сохранить настройки
        SETTINGS['TGUSER_RMUSER'][str(user_id)] = (
            user_name, user_id_rm, str(user))
        await save_settings()
        await message.bot.send_message(message.from_user.id, f'Пользователь Redmine {user} сопоставлен пользователю @{user_name} (id: {user_id})', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['deluser'])
async def process_deluser_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if await is_user_bot_admin(message):
        global SETTINGS
        user_id = message.text.split('/deluser', 1)[1].strip()
        if user_id in SETTINGS['TGUSER_RMUSER'].keys():
            usr = SETTINGS['TGUSER_RMUSER'][user_id]
            SETTINGS['TGUSER_RMUSER'].pop(user_id)
            save_settings()
            await message.bot.send_message(message.from_user.id, f'Пользователь <i>{usr}</i> удален', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)
        else:
            await message.bot.send_message(message.from_user.id, f'Пользователь с указанным id не зарегистрирован!', parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['settings'])
async def process_settings_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if await is_user_bot_admin(message):
        for k in SETTINGS.keys():
            msg = f'<b>{k}</b>:\n'
            if isinstance(SETTINGS[k], dict):
                for j in SETTINGS[k].keys():
                    msg += j + ' ' + str(SETTINGS[k][j]) + '\n'
                pass
            else:
                msg = f'<b>{k}</b>: {str(SETTINGS[k])}'
            await message.bot.send_message(message.from_user.id, msg, parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['groups'])
async def groups_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    if await is_user_bot_admin(message):
        try:
            with open(groups_filename, encoding='utf-8') as f:
                groups = json.load(f)
                f.close
        except:
            return

        for k in groups.keys():
            msg = f'<b>{groups[k]}</b> (id: {k}):\n'
            await message.bot.send_message(message.from_user.id, msg, parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

    elif await is_user_rm_user(message):
        await user_not_admin(message)

    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(commands=['new'])
async def add_new_issue_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    kboard = kb.admin_kb if await is_user_bot_admin(message) else kb.user_kb

    # пользователь, в т.ч. и адиминистратор, должен быть сопоставлен с пользователями Redmine
    if not await is_user_rm_user(message):

        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)
        return

    # Контроль правильности начальных условий и синтаксиса команды
    # получить заголовок задачи
    subject = message.text.split('/new', 1)[1].strip()
    if subject == '':
        await message.bot.send_message(message.from_user.id,
                                       'Задача Redmine не создана!\nНе указан заголовок для создаваемой задачи!',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        return

    replyed_msg = message.reply_to_message

    if replyed_msg == None:
        # Если сообщение в личном чате с ботом и сообщение - это не ответ на другое сообщение, то:
        if message.chat.type == 'private':
            # закешировать команду чтобы ИЛИ обработчик следующеего сообщения (с данными для задачи, если оно существует) взял команду из кэша,
            # ИЛИ отработала периодическая процедура очистки кэша
            global commands_cache
            key = message.from_user.id
            val = [message.date, 'new', subject, True]
            commands_cache[key] = val
            return

        await message.bot.send_message(message.from_user.id,
                                       'Задача Redmine не создана!\nКоманду необходимо вводить в ответ на сообщение, содержащее данные для создаваемой задачи!',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        return

    await add_new_issue(message, replyed_msg, kboard, subject)


# непосредственно создает задачу Redmine
async def add_new_issue(message: types.Message, replyed_msg, kboard, subject, fwd2private=True):

    if not replyed_msg.content_type in ['document', 'photo', 'text']:
        await message.bot.send_message(message.from_user.id,
                                       'Задача Redmine не создана!\nКоманду необходимо вводить в ответ на сообщение, содержащее текст, файл или изображение!',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        return

    # переслать в личку сообщение для задачи, чтобы было
    if fwd2private:
        await replyed_msg.forward(message.from_user.id)

    # получить описание задачи, создать временные дирректории для файлов сохранить в них файлы
    uploads = []
    msg_tmpdir = ''
    if replyed_msg.content_type in ['text']:
        description = replyed_msg.text

    elif replyed_msg.content_type in ['document', 'photo']:
        description = replyed_msg.caption
        msg_tmpdir = await create_tmp_dir(message)
        # сохранить файлы для задачи
        uploads = await save_tmp_file(message, replyed_msg, msg_tmpdir)

    description = '' if description == None else description

    # получить проект Redmine для текущего чата
    project_name = SETTINGS['CHAT_PROJECT'].get(
        str(message.chat.id), SETTINGS['DEFAULT_PROJECT'])[1]

    # получить id пользователя Redmine
    userinfo = SETTINGS['TGUSER_RMUSER'][str(message.from_user.id)]
    assigned_to_id = userinfo[1]

    # создать задачу
    issue, status = await create_issue(project_name, subject, description, assigned_to_id, uploads)
    if status == 'OK':
        notes = f'Задача создана из чата Telegram "{message.chat.full_name}" ({message.chat.id}) пользователем {str(userinfo)}. Оригинальное описание:\n\n{description}.'
        await update_issue(resource_id=issue.id, assigned_to_id=assigned_to_id, notes=notes)
        await message.bot.send_message(message.from_user.id,
                                       f'Задача Redmine {issue.id} <a href="{SETTINGS["RMADRESS"]}issues/{issue.id}">{issue.subject}</a> успешно создана в проекте <b>{str(issue.project)}</b>!\nОтредактируйте задачу при необходимости.',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        lg.log(20, f"Создана задача id: {issue.id}")

    else:
        await message.bot.send_message(message.from_user.id,
                                       f'Ошибка создания задачи Redmine: {status}',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        lg.log(40, f"Ошибка создания задачи")

    await rm_tmp_dir(msg_tmpdir)


@ dp.message_handler(commands=['update'])
async def upd_issue_command(message: types.Message):
    if not await fwd_and_dell(message):
        return

    kboard = kb.admin_kb if await is_user_bot_admin(message) else kb.user_kb

    # пользователь, в т.ч. и адиминистратор, должен быть сопоставлен с пользователями Redmine
    if not await is_user_rm_user(message):
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)
        return

    # Контроль правильности начальных условий и синтаксиса команды
    # получить id задачи
    issue_id = message.text.split('/update', 1)[1].strip()
    if issue_id == '':
        await message.bot.send_message(message.from_user.id,
                                       'Задача Redmine не обновлена!\nНе указан идентификатор задачи!',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        return
    else:
        try:
            issue_id = int(issue_id)
        except:
            await message.bot.send_message(message.from_user.id,
                                           'Задача Redmine не обновлена!\nНекорректный идентификатор задачи!',
                                           parse_mode=types.ParseMode.HTML, reply_markup=kboard)
            return

    replyed_msg = message.reply_to_message
    if replyed_msg == None:
        # Если сообщение в личном чате с ботом и сообщение - это не ответ на другое сообщение, то:
        if message.chat.type == 'private':
            # закешировать команду чтобы ИЛИ обработчик следующеего сообщения (с данными для задачи, если оно существует) взял команду из кэша,
            # ИЛИ отработала периодическая процедура очистки кэша
            global commands_cache
            key = message.from_user.id
            val = [message.date, 'update', issue_id, True]
            commands_cache[key] = val
            return

        await message.bot.send_message(message.from_user.id,
                                       'Задача Redmine не обновлена!\nКоманду необходимо вводить в ответ на сообщение, содержащее данные для обновляемой задачи!',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        return

    await upd_issue_data(message, replyed_msg, kboard, issue_id)


# непосредственно создает комментарий Redmine
async def upd_issue_data(message: types.Message, replyed_msg, kboard, issue_id, fwd2private=True):
    if not replyed_msg.content_type in ['document', 'photo', 'text']:
        await message.bot.send_message(message.from_user.id,
                                       'Задача Redmine не обновлена!\nКоманду необходимо вводить в ответ на сообщение, содержащее текст, файл или изображение!',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        return

    # переслать в личку сообщение для задачи, чтобы было
    if fwd2private:
        await replyed_msg.forward(message.from_user.id)

    # получить описание комментария, создать временные дирректории для файлов сохранить в них файлы
    uploads = []
    msg_tmpdir = ''
    if replyed_msg.content_type in ['text']:
        description = replyed_msg.text

    elif replyed_msg.content_type in ['document', 'photo']:
        description = replyed_msg.caption
        msg_tmpdir = await create_tmp_dir(message)
        # сохранить файлы для задачи
        uploads = await save_tmp_file(message, replyed_msg, msg_tmpdir)

    description = '' if description == None else description

    # обновить задачу
    userinfo = SETTINGS['TGUSER_RMUSER'][str(message.from_user.id)]
    assigned_to_id = userinfo[1]
    description = f'Комментарий добавлен из чата Telegram "{message.chat.full_name}" пользователем {str(userinfo)}:\n' + \
        description
    issue, status = await update_issue(resource_id=issue_id, assigned_to_id=assigned_to_id, notes=description, uploads=uploads)
    if issue:

        await message.bot.send_message(message.from_user.id,
                                       f'Задача Redmine <a href="{SETTINGS["RMADRESS"]}issues/{issue_id}">{issue_id}</a> успешно обновлена.',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        lg.log(20, f"Откорректирована задача id: {issue_id}")

    else:
        await message.bot.send_message(message.from_user.id,
                                       f'Ошибка ообновления задачи Redmine: {status}',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        lg.log(40, f"Ошибка изменения задачи id: {issue_id}")

    await rm_tmp_dir(msg_tmpdir)


@ dp.message_handler(commands=['broadcast'])
async def broadcast_command(message: types.Message):

    if await is_user_bot_admin(message):
        msg_txt = message.text.split('/broadcast', 1)[1].strip()

        if msg_txt == '':
            await message.bot.send_message(message.from_user.id,
                                           'Сообщение не может быть отправлено: не указан текст сообщения',
                                           parse_mode=types.ParseMode.HTML, reply_markup=kb.admin_kb)

        if await is_group(message):
            if not await fwd_and_dell(message):
                return

            current_grouop = {str(message.chat.id): message.chat.full_name}
            await broadcast(message, current_grouop, msg_txt)
        else:
            await broadcast(message, GROUPS, msg_txt)

    elif await is_user_rm_user(message):
        await user_not_admin(message)
    else:
        await message.bot.send_message(message.from_user.id, messages['notregisterd_msg'], parse_mode=types.ParseMode.HTML)


@ dp.message_handler(is_fwd=True, is_private=True, content_types=types.ContentType.ANY)
async def fwd_private_message(message: types.Message):

    global commands_cache
    if message.from_user.id in commands_cache:
        kboard = kb.admin_kb if await is_user_bot_admin(message) else kb.user_kb
        uid = message.from_user.id
        # время кэшированной команды и пересланного сообщения не должно различаться [более чем на 1 секунду]
        time_delta = datetime.timedelta(seconds=1)
        cached_date = commands_cache[uid][0]
        if (message.date-cached_date) > time_delta:
            return
        # заблокировать удаление периодической командой
        commands_cache[uid][3] = False
        cached_command = commands_cache[uid][1]
        cached_args = commands_cache[uid][2]
        if cached_command == 'new':
            await add_new_issue(message, message, kboard, cached_args, False)

        elif cached_command == 'update':
            await upd_issue_data(message, message, kboard, cached_args, False)

        try:
            commands_cache.pop(uid)
        except:
            pass


@ dp.message_handler(content_types=types.ContentType.ANY)
async def any_other_message(message: types.Message):
    kboard = kb.admin_kb if await is_user_bot_admin(message) else kb.user_kb
    if not await is_group(message):

        await message.bot.send_message(message.from_user.id, 'Введите команду. Для получения доступных комманд введите <b>/help</b>',
                                       parse_mode=types.ParseMode.HTML, reply_markup=kboard)
        return

    if str(message.chat.id) in GROUPS.keys() and message.chat.full_name == GROUPS[str(message.chat.id)]:
        return

    await add_group(message)


# endregion

# region обработчики ошибок


@ dp.errors_handler(exception=BotBlocked)
async def error_bot_blocked(update: types.Update, exception: BotBlocked):
    # Update: объект события от Telegram. Exception: объект исключения

    lg.log(
        40, f"Меня заблокировал пользователь!\nСообщение: {update}\nОшибка: {exception}")

    # Такой хэндлер должен всегда возвращать True, если дальнейшая обработка не требуется.
    return True

# endregion


if __name__ == '__main__':
    load_settings()
    init_messages()
    dp.loop.create_task(periodic_clean_commands_cache())
    executor.start_polling(dp, skip_updates=True)
