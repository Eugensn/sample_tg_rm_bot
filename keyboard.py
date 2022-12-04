from aiogram.types import ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton,InlineKeyboardMarkup, InlineKeyboardButton

button_start = KeyboardButton('/start')
button_help = KeyboardButton('/help')
button_project = KeyboardButton('/project')
button_groups = KeyboardButton('/groups')
button_settings = KeyboardButton('/settings ')

user_kb = ReplyKeyboardMarkup(resize_keyboard=True)
user_kb.row(button_help, button_project)

admin_kb = ReplyKeyboardMarkup(resize_keyboard=True)
admin_kb.row(button_help, button_project)
admin_kb.row(button_settings, button_groups)

