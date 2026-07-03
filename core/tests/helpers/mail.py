# tests/helpers/mail.py
from django.core import mail


def last_mail():

    assert mail.outbox

    return mail.outbox[-1]


def mail_count():

    return len(mail.outbox)


def clear_mailbox():

    mail.outbox.clear()