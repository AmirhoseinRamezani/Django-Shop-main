def gateway_success():
    return {
        "Status": 100,
        "RefID": "123456",
    }


def gateway_failed():
    return {
        "Status": -1,
    }


def webhook_success():
    return {
        "ok": True,
    }


def webhook_failed():
    return {
        "ok": False,
    }