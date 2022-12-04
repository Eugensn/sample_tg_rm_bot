# пример настройки фильтров
# на данный момент в проекте кастомные фильтры не используются
from aiogram import types
from aiogram.dispatcher.filters import BoundFilter




# отправитель сообщения является администратором чата
class IsAdminFilter(BoundFilter):
    key = 'is_admin'

    def __init__(self, is_admin):
        self.is_admin = is_admin

    async def check(self, message: types.message):
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.is_chat_admin()


# бот является администратором чата
class IsBotAdminFilter(BoundFilter):
    key = 'is_bot_admin'

    def __init__(self, is_bot_admin):
        self.is_bot_admin = is_bot_admin

    async def check(self, message: types.message):
        member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
        return member.is_chat_admin()


# сообщение из группы
class IsGroupFilter(BoundFilter):
    key = 'is_group'

    def __init__(self, is_group):
        self.is_group = is_group

    async def check(self, message: types.message):

        return message.chat.type == 'group'

# сообщение из приватного чата
class IsPrivateFilter(BoundFilter):
    key = 'is_private'

    def __init__(self, is_private):
        self.is_private = is_private

    async def check(self, message: types.message):

        return message.chat.type == 'private'

# сообщение переслано
class IsFwdFilter(BoundFilter):
    key = 'is_fwd'

    def __init__(self, is_fwd):
        self.is_fwd = is_fwd

    async def check(self, message: types.message):            
        return message.forward_date != None

