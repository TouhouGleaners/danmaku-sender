from peewee import Model, DatabaseProxy, CharField, IntegerField, TextField, FloatField


db = DatabaseProxy()

class BaseModel(Model):
    """模型基类"""
    class Meta:
        database = db


class SentDanmaku(BaseModel):
    dmid = CharField(primary_key=True)
    cid = IntegerField()
    bvid = CharField()
    msg = TextField()
    progress = IntegerField()
    mode = IntegerField()
    fontsize = IntegerField()
    color = IntegerField()
    ctime = FloatField()
    is_visible = IntegerField()
    status = IntegerField(default=0)

    class Meta:
        table_name = 'sent_danmaku'
        indexes = (
            (('cid', 'status'), False),
        )