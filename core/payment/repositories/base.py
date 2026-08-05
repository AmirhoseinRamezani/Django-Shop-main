# payment/repositories/base.py

class BaseRepository:

    model = None

    @classmethod
    def queryset(cls):
        return cls.model.objects.all()

    @classmethod
    def get(cls, pk):
        return cls.queryset().get(pk=pk)

    @classmethod
    def create(cls, **kwargs):
        return cls.model.objects.create(**kwargs)
    
    @classmethod
    def lock(cls, pk):

        return (
            cls.model.objects
            .select_for_update()
            .get(pk=pk)
        )

    @classmethod
    def save(cls, instance, update_fields=None):
        instance.save(update_fields=update_fields)
        return instance
    
    