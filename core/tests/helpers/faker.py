# tests/helpers/faker.py
from faker import Faker

fake = Faker("fa_IR")


def phone():

    return fake.phone_number()


def email():

    return fake.email()


def name():

    return fake.name()


def address():

    return fake.address()