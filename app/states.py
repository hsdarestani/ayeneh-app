from aiogram.fsm.state import State, StatesGroup


class SelfSurvey(StatesGroup):
    answering = State()


class FriendSurvey(StatesGroup):
    choosing_relation = State()
    answering = State()


class PaymentFlow(StatesGroup):
    waiting_receipt = State()
