"""Authorization at the Telegram handler boundary (not just hidden buttons).

Checks are applied to ConversationHandler children as well as regular handlers.
The database queries are performed off the asyncio event loop.
"""
import asyncio
import logging
import re
from telegram.ext import CallbackQueryHandler, MessageHandler, CommandHandler
from settings import SUPER_ADMIN_ID
from database import Database

log = logging.getLogger(__name__)

# Administrative actions can also be invoked with forged callback_data.
ADMIN_CALLBACKS = re.compile(
    r'^(?:admin_|add_new_admin$|del_pay_method_|add_pay_method_|'
    r'confirm_admin_|delete_monitor_node$|update_monitor_node$)'
)
ADMIN_MESSAGES = {
    'get_new_user_id', 'get_new_user_days', 'admin_set_limit_handler',
    'admin_set_days_handler', 'admin_search_handler', 'admin_broadcast_send',
    'admin_report_by_uid_handler', 'admin_agent_port_input',
    'admin_backup_restore_handler', 'admin_key_restore_handler',
    'get_pay_network', 'get_pay_address', 'get_pay_holder',
    'admin_search_servers_by_uid_handler',
}
# Captured numerical IDs in callback data. Server ID is at end of act_* except
# act_checkhost_{id}_{IP}; these prefixes are deliberately explicit.
SERVER_ID = (
    re.compile(r'^detail_(\d+)(?:_|$)'),
    re.compile(r'^act_[a-z]+_(\d+)(?:_|$)'),
    re.compile(r'^setdns_[a-z]+_(\d+)$'),
    re.compile(r'^toggle_active_(\d+)$'),
    re.compile(r'^srv_multidel_toggle_(\d+)$'),
    re.compile(r'^cmd_terminal_(\d+)$'),
    re.compile(r'^admin_detail_(\d+)$'),
)
CONFIG_ID = (
    re.compile(r'^(?:test_conf|view_conf|del_conf|conf_detail|copy_conf|qr_conf|manage_sub|update_sub|del_sub_full|get_sub_links)_(\d+)(?:_|$)'),
    re.compile(r'^del_list_item_(\d+)(?:_|$)'),
)
GROUP_ID = (re.compile(r'^delgroup_(\d+)$'),)
CHANNEL_ID = (re.compile(r'^delchan_(\d+)$'),)


def _access_sync(uid, data, callback_name):
    db = Database()
    if not uid:
        return False
    if (ADMIN_CALLBACKS.match(data or '') or callback_name in ADMIN_MESSAGES) and uid != SUPER_ADMIN_ID:
        return False
    if uid != SUPER_ADMIN_ID:
        allowed, _ = db.check_access(uid, SUPER_ADMIN_ID)
        if not allowed:
            return False
        if data:
            for table, patterns in [('servers', SERVER_ID), ('tunnel_configs', CONFIG_ID),
                                    ('groups', GROUP_ID), ('channels', CHANNEL_ID)]:
                for pattern in patterns:
                    hit = pattern.match(data)
                    if hit and not db.owns_resource(table, int(hit.group(1)), uid):
                        return False
    return True


async def _is_allowed(update, callback):
    # Starting a conversation is intentionally allowed for new users.
    if getattr(callback, '__name__', '') == 'start':
        return True
    uid = getattr(getattr(update, 'effective_user', None), 'id', None)
    data = getattr(getattr(update, 'callback_query', None), 'data', '') or ''
    try:
        return await asyncio.to_thread(_access_sync, uid, data, getattr(callback, '__name__', ''))
    except Exception:
        log.exception('Authorization failed closed')
        return False


class SecureCallbackQueryHandler(CallbackQueryHandler):
    async def handle_update(self, update, application, check_result, context):
        if not await _is_allowed(update, self.callback):
            if update.callback_query:
                await update.callback_query.answer('⛔ دسترسی مجاز نیست.', show_alert=True)
            return None
        return await super().handle_update(update, application, check_result, context)


class SecureMessageHandler(MessageHandler):
    async def handle_update(self, update, application, check_result, context):
        if not await _is_allowed(update, self.callback):
            if update.effective_message:
                await update.effective_message.reply_text('⛔ دسترسی مجاز نیست.')
            return None
        return await super().handle_update(update, application, check_result, context)


class SecureCommandHandler(CommandHandler):
    async def handle_update(self, update, application, check_result, context):
        if not await _is_allowed(update, self.callback):
            if update.effective_message:
                await update.effective_message.reply_text('⛔ دسترسی مجاز نیست.')
            return None
        return await super().handle_update(update, application, check_result, context)
