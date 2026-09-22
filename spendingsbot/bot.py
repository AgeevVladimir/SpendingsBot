from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from .models import Spending
from .parsers import get_command_args, is_valid_iso_date, parse_shared_members, split_spending_arguments
from .repository import DEFAULT_MEMBER_NAMES, DEFAULT_TRIP_NAME, SpendingsRepository
from .settlement import calculate_settlement

logger = logging.getLogger(__name__)

AMOUNT_PATTERN = re.compile(r'^(?:0\.(?:0?[1-9]|[1-9]\d)|[1-9]\d*(?:\.\d{1,2})?)$')

MENU_ADD_SPENDING = '➕ Add spending'
MENU_TODAY = '📅 Today spendings'
MENU_PERSONAL = '🧍 Personal spendings'
MENU_PERSONAL_PAYMENTS = '💳 Personal payments'
MENU_ALL = '🌍 All spendings'
MENU_SETTLEMENT = '💸 Show current settleup'
MENU_UNDO = '↩️ Undo last spending'


def _new_wizard() -> dict[str, object]:
    return {
        'amount': None,
        'payer': None,
        'description': None,
        'selected': set(),
        'members': [],
        'awaiting_amount': False,
        'awaiting_description': False,
    }


def _wizard(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    return context.user_data.setdefault('spending_wizard', _new_wizard())


def _clear_wizard(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop('spending_wizard', None)


def _get_bound_member(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    value = context.user_data.get('member_name')
    return str(value) if value else None


def _set_bound_member(context: ContextTypes.DEFAULT_TYPE, member_name: str) -> None:
    context.user_data['member_name'] = member_name


def _encode_member(member: str) -> str:
    return member.replace(' ', '_')


def _decode_member(value: str) -> str:
    return value.replace('_', ' ')


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(MENU_ADD_SPENDING, callback_data='menu:add_spending')],
            [InlineKeyboardButton(MENU_TODAY, callback_data='report:today')],
            [InlineKeyboardButton(MENU_PERSONAL, callback_data='report:personal')],
            [InlineKeyboardButton(MENU_PERSONAL_PAYMENTS, callback_data='report:payments')],
            [InlineKeyboardButton(MENU_ALL, callback_data='report:all')],
            [InlineKeyboardButton(MENU_SETTLEMENT, callback_data='report:settlement')],
        ]
    )


def _persistent_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(MENU_ADD_SPENDING)],
            [KeyboardButton(MENU_UNDO), KeyboardButton(MENU_TODAY)],
            [KeyboardButton(MENU_PERSONAL), KeyboardButton(MENU_PERSONAL_PAYMENTS)],
            [KeyboardButton(MENU_ALL), KeyboardButton(MENU_SETTLEMENT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
    )


def _person_picker_keyboard(members: list[str], mode: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for member in members:
        current_row.append(InlineKeyboardButton(member, callback_data=f'report:person:{mode}:{_encode_member(member)}'))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([InlineKeyboardButton('✖️ Cancel', callback_data='wizard:cancel')])
    return InlineKeyboardMarkup(rows)


def _cancel_only_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton('✖️ Cancel', callback_data='wizard:cancel')]])


def _member_keyboard(members: list[str], selected: set[str] | None = None, payer_mode: bool = False) -> InlineKeyboardMarkup:
    selected = selected or set()
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []

    for member in members:
        encoded = _encode_member(member)
        label = member
        callback = f'payer:{encoded}' if payer_mode else f'toggle:{encoded}'
        if not payer_mode and member in selected:
            label = f'{member} ✓'
        current_row.append(InlineKeyboardButton(label, callback_data=callback))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    if not payer_mode:
        rows.append(
            [
                InlineKeyboardButton('✅ Done', callback_data='wizard:done'),
                InlineKeyboardButton('✖️ Cancel', callback_data='wizard:cancel'),
            ]
        )
    else:
        rows.append([InlineKeyboardButton('✖️ Cancel', callback_data='wizard:cancel')])

    return InlineKeyboardMarkup(rows)


async def _reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
    preserve_in_history: bool = False,
) -> None:
    if not update.effective_chat:
        return

    previous_id = context.user_data.get('last_bot_message_id')
    if previous_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=int(previous_id))
        except Exception:
            pass

    target_markup = reply_markup if reply_markup is not None else _persistent_menu_keyboard()
    sent = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=target_markup,
    )
    if preserve_in_history:
        context.user_data.pop('last_bot_message_id', None)
    else:
        context.user_data['last_bot_message_id'] = sent.message_id
    preserve_user_message_once = bool(context.user_data.pop('preserve_user_message_once', False))
    message = update.message
    if message and message.from_user and not message.from_user.is_bot and not preserve_user_message_once:
        try:
            await message.delete()
        except Exception:
            pass


def _repository(context: ContextTypes.DEFAULT_TYPE) -> SpendingsRepository:
    return context.application.bot_data['repository']


async def _repo_call(context: ContextTypes.DEFAULT_TYPE, method_name: str, *args):
    repository = _repository(context)
    method = getattr(repository, method_name)
    return await asyncio.to_thread(method, *args)


async def _ensure_default_trip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    await _repo_call(context, 'ensure_default_trip', update.effective_chat.id, DEFAULT_TRIP_NAME, DEFAULT_MEMBER_NAMES)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_wizard(context)
    await _ensure_default_trip(update, context)
    await _reply(update, context, f'Путешествие "{DEFAULT_TRIP_NAME}" готово.\nВыберите действие ниже.')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(
        update,
        context,
        'How to use:\n'
        '1) Press ➕ Add spending\n'
        '2) Enter amount + description in one message (example: 200 restaurant 2 day)\n'
        '3) Choose payer and shared members\n\n'
        'Commands:\n'
        '/start - show main menu\n'
        '/help - show this help\n'
        '/iam <member> - bind your Telegram user to a member\n'
        '/undo - remove the latest spending (your own if bound)\n'
        '/members - list members\n'
        '/spendings - list all spendings\n'
        '/cancel - cancel current add-spending flow',
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_wizard(context)
    await _reply(update, context, 'Current flow cancelled.')


def _find_member_match(members: list[str], raw_name: str) -> str | None:
    clean = (raw_name or '').strip()
    if not clean:
        return None

    for member in members:
        if member.casefold() == clean.casefold():
            return member

    starts_with = [member for member in members if member.casefold().startswith(clean.casefold())]
    if len(starts_with) == 1:
        return starts_with[0]
    return None


async def iam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return

    try:
        state = await _repo_call(context, 'read_trip', update.effective_chat.id)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    if not state.members:
        await _reply(update, context, 'No members configured yet.')
        return

    raw_name = get_command_args(update.effective_message.text if update.effective_message else '')
    if not raw_name:
        current = _get_bound_member(context)
        if current and current in state.members:
            await _reply(update, context, f'You are currently linked as: {current}')
        else:
            await _reply(update, context, 'Set your member with /iam <name>\nAvailable: ' + ', '.join(state.members))
        return

    matched = _find_member_match(state.members, raw_name)
    if not matched:
        await _reply(update, context, 'Unknown member. Available: ' + ', '.join(state.members))
        return

    _set_bound_member(context, matched)
    await _reply(update, context, f'✅ Linked. Your member is now: {matched}')


async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return

    payer = _get_bound_member(context)
    try:
        removed = await _repo_call(context, 'remove_last_spending', update.effective_chat.id, payer)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    await _reply(
        update,
        context,
        f'↩️ Removed: {removed.date} | €{removed.amount_eur:.2f} | {removed.description} '
        f'| payer: {removed.payer} | shared: {", ".join(removed.shared_with)}',
    )


async def newtrip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_default_trip(update, context)
    await _reply(update, context, f'Trip is fixed and always active: "{DEFAULT_TRIP_NAME}"')


async def addmember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member = get_command_args(update.effective_message.text if update.effective_message else '')
    if not member:
        await _reply(update, context, 'Usage: /addmember <name>')
        return

    try:
        await _repo_call(context, 'add_member', update.effective_chat.id, member)
        await _reply(update, context, f'Member "{member}" added.')
    except ValueError as error:
        await _reply(update, context, str(error))


async def members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        state = await _repo_call(context, 'read_trip', update.effective_chat.id)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    if not state.trip:
        await _reply(update, context, 'Create a trip first with /newtrip')
        return
    if not state.members:
        await _reply(update, context, 'No members yet. Use /addmember')
        return

    await _reply(update, context, 'Members:\n' + '\n'.join(f'- {member}' for member in state.members))


async def addspending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = get_command_args(update.effective_message.text if update.effective_message else '')
    parts = split_spending_arguments(raw)
    if not parts:
        await _reply(update, context, 'Usage: /addspending <amount>; <date>; <description>; <payer>; <shared1,shared2>')
        return

    amount_raw, date_raw, description, payer, shared_raw = parts
    if not AMOUNT_PATTERN.fullmatch(amount_raw):
        await _reply(update, context, 'Amount must be a positive number in EUR with up to 2 decimals.')
        return

    shared_with = parse_shared_members(shared_raw)
    if shared_with is None:
        await _reply(update, context, 'Shared members list has invalid quotes.')
        return

    amount_eur = float(amount_raw)
    if amount_eur <= 0:
        await _reply(update, context, 'Amount must be a positive number in EUR.')
        return
    if not is_valid_iso_date(date_raw):
        await _reply(update, context, 'Date must be in format YYYY-MM-DD.')
        return
    if not description or not payer or not shared_with:
        await _reply(update, context, 'Description, payer and shared members are required.')
        return

    try:
        await _repo_call(
            context,
            'add_spending',
            update.effective_chat.id,
            Spending(
                amount_eur=amount_eur,
                date=date_raw,
                description=description,
                payer=payer,
                shared_with=shared_with,
            ),
        )
        await _reply(update, context, 'Spending added.')
    except ValueError as error:
        await _reply(update, context, str(error))


async def spendings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        state = await _repo_call(context, 'read_trip', update.effective_chat.id)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    if not state.trip:
        await _reply(update, context, 'Create a trip first with /newtrip')
        return
    if not state.spendings:
        await _reply(update, context, 'No spendings yet.')
        return

    lines = [
        f'{index}. {spending.date} - €{spending.amount_eur:.2f} - {spending.description} (paid by {spending.payer}, shared: {", ".join(spending.shared_with)})'
        for index, spending in enumerate(state.spendings, start=1)
    ]
    total = sum(spending.amount_eur for spending in state.spendings)
    await _reply(update, context, '\n'.join(lines) + f'\n\nTOTAL: €{total:.2f}')


async def closetrip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        settlements = await _repo_call(context, 'close_trip', update.effective_chat.id)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    if not settlements:
        await _reply(update, context, 'Trip closed. Everybody is settled up.')
        return

    lines = [
        f'{settlement.from_member} owes {settlement.to_member} €{settlement.amount_eur:.2f}'
        for settlement in settlements
    ]
    await _reply(update, context, 'Trip closed. Settlements:\n' + '\n'.join(lines))


async def _show_person_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str = 'spendings') -> None:
    if not update.effective_chat:
        return

    await _ensure_default_trip(update, context)

    try:
        state = await _repo_call(context, 'read_trip', update.effective_chat.id)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    members: list[str] = []
    seen: set[str] = set()

    for member in state.members:
        clean = (member or '').strip()
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        members.append(clean)

    if not members:
        for spending in state.spendings:
            candidates = [spending.payer, *spending.shared_with]
            for candidate in candidates:
                clean = (candidate or '').strip()
                if not clean:
                    continue
                key = clean.casefold()
                if key in seen:
                    continue
                seen.add(key)
                members.append(clean)

    if not members:
        members = list(DEFAULT_MEMBER_NAMES)

    title = 'Choose a person for personal spendings:' if mode == 'spendings' else 'Choose a person for personal payments:'
    await _reply(update, context, title, reply_markup=_person_picker_keyboard(members, mode))


async def _show_person_spendings(update: Update, context: ContextTypes.DEFAULT_TYPE, member_name: str) -> None:
    if not update.effective_chat:
        return

    try:
        report = await _repo_call(context, 'summarize_spendings', update.effective_chat.id, 'my', member_name)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    if not report['spendings']:
        await _reply(update, context, f'No spendings for {member_name} yet.', preserve_in_history=True)
        return

    lines = [
        f'{index}. {spending.date} — €{spending.amount_eur:.2f} — {spending.description} '
        f'(payer: {spending.payer}, shared: {", ".join(spending.shared_with)})'
        for index, spending in enumerate(report['spendings'], start=1)
    ]
    await _reply(
        update,
        context,
        f'Personal spendings: {member_name}\n' + '\n'.join(lines) + f'\n\nTOTAL: €{report["total_eur"]:.2f}',
        preserve_in_history=True,
    )


async def _show_person_payments(update: Update, context: ContextTypes.DEFAULT_TYPE, member_name: str) -> None:
    if not update.effective_chat:
        return

    try:
        report = await _repo_call(context, 'summarize_spendings', update.effective_chat.id, 'payments', member_name)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    if not report['spendings']:
        await _reply(update, context, f'No payments by {member_name} yet.', preserve_in_history=True)
        return

    lines = [
        f'{index}. {spending.date} — €{spending.amount_eur:.2f} — {spending.description} '
        f'(shared: {", ".join(spending.shared_with)})'
        for index, spending in enumerate(report['spendings'], start=1)
    ]
    await _reply(
        update,
        context,
        f'Personal payments: {member_name}\n' + '\n'.join(lines) + f'\n\nTOTAL PAID: €{report["total_eur"]:.2f}',
        preserve_in_history=True,
    )


async def _show_report(update: Update, context: ContextTypes.DEFAULT_TYPE, scope: str) -> None:
    if not update.effective_chat:
        return

    await _ensure_default_trip(update, context)

    member_name = None
    if scope == 'my':
        try:
            state = await _repo_call(context, 'read_trip', update.effective_chat.id)
        except ValueError as error:
            await _reply(update, context, str(error))
            return

        if not state.members:
            await _reply(update, context, 'No members configured yet.')
            return

        bound = _get_bound_member(context)
        if bound and bound in state.members:
            member_name = bound
        else:
            first_name = (update.effective_user.first_name if update.effective_user else '') or ''
            guessed = _find_member_match(state.members, first_name)
            if guessed:
                _set_bound_member(context, guessed)
                member_name = guessed
            else:
                await _reply(
                    update,
                    context,
                    'I can\'t map your Telegram profile to a member yet. '
                    'Use /iam <name>.\nAvailable: ' + ', '.join(state.members),
                )
                return

    try:
        report = await _repo_call(context, 'summarize_spendings', update.effective_chat.id, scope, member_name)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    if not report['spendings']:
        if scope == 'today':
            await _reply(update, context, 'No spendings for today.', preserve_in_history=True)
        elif scope == 'my':
            await _reply(update, context, f'No spendings for {member_name} yet.', preserve_in_history=True)
        else:
            await _reply(update, context, 'No spendings yet.', preserve_in_history=True)
        return

    lines = [
        f'{index}. {spending.date} — €{spending.amount_eur:.2f} — {spending.description} '
        f'(payer: {spending.payer}, shared: {", ".join(spending.shared_with)})'
        for index, spending in enumerate(report['spendings'], start=1)
    ]
    title = 'Today spendings' if scope == 'today' else 'Personal spendings' if scope == 'my' else 'All spendings'
    await _reply(
        update,
        context,
        f'{title}:\n' + '\n'.join(lines) + f'\n\nTOTAL: €{report["total_eur"]:.2f}',
        preserve_in_history=True,
    )


async def _start_spending_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_default_trip(update, context)
    await _request_custom_amount(update, context)


async def _request_custom_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(
        update,
        context,
        'Enter amount and description in one message, for example: 200 restaurant 2 day',
        reply_markup=_cancel_only_keyboard(),
    )
    wizard = _wizard(context)
    wizard['amount'] = None
    wizard['payer'] = None
    wizard['description'] = None
    wizard['selected'] = set()
    wizard['awaiting_amount'] = True
    wizard['awaiting_description'] = False


async def _request_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, context, 'Enter a short description for this spending, for example: dinner, taxi, groceries')
    wizard = _wizard(context)
    wizard['awaiting_description'] = True
    wizard['awaiting_amount'] = False


async def _select_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    try:
        state = await _repo_call(context, 'read_trip', update.effective_chat.id)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    wizard = _wizard(context)
    wizard['members'] = list(state.members)
    await _reply(update, context, 'Who paid?', reply_markup=_member_keyboard(state.members, payer_mode=True))


async def _select_shared(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wizard = _wizard(context)
    members = list(wizard.get('members', []))
    if not members:
        if not update.effective_chat:
            return
        try:
            state = await _repo_call(context, 'read_trip', update.effective_chat.id)
        except ValueError as error:
            await _reply(update, context, str(error))
            return
        members = list(state.members)
        wizard['members'] = members

    await _reply(update, context, 'Choose people to share with:', reply_markup=_member_keyboard(members, wizard.get('selected', set())))


async def _finish_spending_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wizard = context.user_data.get('spending_wizard', {})
    amount = wizard.get('amount')
    payer = wizard.get('payer')
    description = wizard.get('description')
    selected = wizard.get('selected', set())

    if amount is None or payer is None or not selected or not description:
        await _reply(update, context, 'The spending is incomplete. Please finish the flow from the beginning.')
        return

    if not update.effective_chat:
        return

    try:
        await _repo_call(
            context,
            'add_spending',
            update.effective_chat.id,
            Spending(
                amount_eur=float(amount),
                date=date.today().isoformat(),
                description=str(description).strip(),
                payer=payer,
                shared_with=sorted(selected),
            ),
        )
        await _reply(
            update,
            context,
            f'Spending saved: €{float(amount):.2f} | {description} | payer: {payer} | shared: {", ".join(sorted(selected))}',
            preserve_in_history=True,
        )
        _clear_wizard(context)
    except ValueError as error:
        await _reply(update, context, str(error))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = getattr(context, 'error', None)
    if error is None:
        logger.warning('Error handler invoked without exception. Update: %s', update)
        return

    logger.error('Unhandled Telegram error while processing update: %s', update, exc_info=error)
    if update is not None and getattr(update, 'effective_message', None) is not None:
        try:
            await update.effective_message.reply_text('The bot hit a temporary issue. Please try again in a moment.')
        except Exception:
            pass



def build_application(bot_token: str, repository: SpendingsRepository) -> Application:
    application = Application.builder().token(bot_token).build()
    application.bot_data['repository'] = repository
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('cancel', cancel))
    application.add_handler(CommandHandler('iam', iam))
    application.add_handler(CommandHandler('undo', undo))
    application.add_handler(CommandHandler('newtrip', newtrip))
    application.add_handler(CommandHandler('addmember', addmember))
    application.add_handler(CommandHandler('members', members))
    application.add_handler(CommandHandler('addspending', addspending))
    application.add_handler(CommandHandler('spendings', spendings))
    application.add_handler(CommandHandler('closetrip', closetrip))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return

    query = update.callback_query
    await query.answer()
    data = query.data or ''

    if data == 'menu:add_spending':
        await _start_spending_wizard(update, context)
        return

    if data == 'menu:members':
        await members(update, context)
        return

    if data == 'report:personal':
        await _show_person_picker(update, context, mode='spendings')
        return

    if data == 'report:payments':
        await _show_person_picker(update, context, mode='payments')
        return

    if data.startswith('amount:'):
        value = data.split(':', 1)[1]
        wizard = _wizard(context)
        wizard['amount'] = float(value)
        wizard['awaiting_amount'] = False
        await _request_description(update, context)
        return

    if data.startswith('payer:'):
        member = _decode_member(data.split(':', 1)[1])
        wizard = _wizard(context)
        wizard['payer'] = member
        await _select_shared(update, context)
        return

    if data.startswith('toggle:'):
        member = _decode_member(data.split(':', 1)[1])
        wizard = _wizard(context)
        selected = wizard.get('selected', set())
        if member in selected:
            selected.remove(member)
        else:
            selected.add(member)
        wizard['selected'] = selected
        members = list(wizard.get('members', []))
        if not members:
            if not update.effective_chat:
                return
            try:
                state = await _repo_call(context, 'read_trip', update.effective_chat.id)
            except ValueError as error:
                await _reply(update, context, str(error))
                return
            members = list(state.members)
            wizard['members'] = members
        try:
            await query.edit_message_text(
                'Choose people to share with:',
                reply_markup=_member_keyboard(members, selected),
            )
        except Exception:
            await _reply(update, context, 'Choose people to share with:', reply_markup=_member_keyboard(members, selected))
        return

    if data.startswith('report:person:'):
        parts = data.split(':', 3)
        if len(parts) != 4:
            await _reply(update, context, 'Unsupported action.')
            return
        mode = parts[2]
        member = _decode_member(parts[3])
        if mode == 'payments':
            await _show_person_payments(update, context, member)
        else:
            await _show_person_spendings(update, context, member)
        return

    if data == 'wizard:done':
        await _finish_spending_wizard(update, context)
        return

    if data == 'wizard:cancel':
        await cancel(update, context)
        return

    if data == 'report:today':
        await _show_report(update, context, 'today')
        return

    if data == 'report:my':
        await _show_person_picker(update, context, mode='spendings')
        return

    if data == 'report:all':
        await _show_report(update, context, 'all')
        return

    if data == 'report:settlement':
        await _show_settlement(update, context)
        return

    await _reply(update, context, 'Unsupported action.')


async def handle_manual_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_message.text:
        return

    text = update.effective_message.text.strip()
    if text.casefold() in {'cancel', 'отмена'}:
        await cancel(update, context)
        return

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await _reply(update, context, 'Please enter amount and description, for example: 200 restaurant 2 day')
        return

    amount_raw, description = parts[0], parts[1].strip()
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', amount_raw):
        await _reply(update, context, 'Please enter a valid amount first, for example: 200 dinner')
        return
    amount = float(amount_raw)
    if amount <= 0:
        await _reply(update, context, 'Amount must be greater than zero.')
        return
    if not description or '\n' in description:
        await _reply(update, context, 'Please add a short single-line description after the amount.')
        return

    wizard = _wizard(context)
    wizard['amount'] = amount
    wizard['description'] = description
    wizard['awaiting_amount'] = False
    wizard['awaiting_description'] = False
    context.user_data['preserve_user_message_once'] = True
    await _select_payer(update, context)


def _parse_amount_description(text: str) -> tuple[float, str] | None:
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None

    amount_raw, description = parts[0], parts[1].strip()
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', amount_raw):
        return None
    amount = float(amount_raw)
    if amount <= 0 or not description or '\n' in description:
        return None
    return amount, description


async def _capture_spending_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    parsed = _parse_amount_description(text)
    if parsed is None:
        return False

    await _ensure_default_trip(update, context)
    amount, description = parsed
    wizard = _wizard(context)
    wizard['amount'] = amount
    wizard['description'] = description
    wizard['awaiting_amount'] = False
    wizard['awaiting_description'] = False
    context.user_data['preserve_user_message_once'] = True
    await _select_payer(update, context)
    return True


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_message.text:
        return

    wizard = context.user_data.get('spending_wizard', {})
    if wizard.get('awaiting_amount'):
        await handle_manual_amount(update, context)
        return

    text = update.effective_message.text.strip()
    if text.casefold() in {'cancel', 'отмена'}:
        await cancel(update, context)
        return

    if await _capture_spending_from_text(update, context, text):
        return

    if text == MENU_ADD_SPENDING:
        await _start_spending_wizard(update, context)
        return
    if text == MENU_UNDO:
        await undo(update, context)
        return
    if text == MENU_TODAY:
        await _show_report(update, context, 'today')
        return
    if text == MENU_PERSONAL:
        await _show_person_picker(update, context, mode='spendings')
        return
    if text == MENU_PERSONAL_PAYMENTS:
        await _show_person_picker(update, context, mode='payments')
        return
    if text == MENU_ALL:
        await _show_report(update, context, 'all')
        return
    if text == MENU_SETTLEMENT:
        await _show_settlement(update, context)
        return
    await _reply(update, context, 'Use the menu buttons below to continue.')


async def _show_settlement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return

    try:
        state = await _repo_call(context, 'read_trip', update.effective_chat.id)
    except ValueError as error:
        await _reply(update, context, str(error))
        return

    if not state.trip:
        await _reply(update, context, 'Create a trip first with /newtrip')
        return
    if not state.members:
        await _reply(update, context, 'No members yet.')
        return
    if not state.spendings:
        await _reply(update, context, 'No spendings yet. Nothing to settle.')
        return

    balances: dict[str, float] = {member: 0.0 for member in state.members}
    for spending in state.spendings:
        if not spending.shared_with:
            continue
        amount = spending.amount_eur
        split = amount / len(spending.shared_with)
        balances[spending.payer] = balances.get(spending.payer, 0.0) + amount
        for member in spending.shared_with:
            balances[member] = balances.get(member, 0.0) - split

    lines = [f'{member}: {balances[member]:+.2f} EUR' for member in state.members]
    settlements = calculate_settlement(state.members, state.spendings)
    if not settlements:
        await _reply(update, context, 'Current balances:\n' + '\n'.join(lines) + '\n\nNobody owes anything.')
        return

    settlement_lines = [
        f'{settlement.from_member} owes {settlement.to_member} €{settlement.amount_eur:.2f}'
        for settlement in settlements
    ]
    await _reply(
        update,
        context,
        'Current balances:\n' + '\n'.join(lines) + '\n\nSettle up:\n' + '\n'.join(settlement_lines),
        preserve_in_history=True,
    )
