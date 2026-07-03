# # base.py
# class BaseFactory(factory.django.DjangoModelFactory):

#     class Meta:
#         abstract = True

#     @classmethod
#     def build_batch_dict(cls, size):

#         return [obj.__dict__ for obj in cls.build_batch(size)]