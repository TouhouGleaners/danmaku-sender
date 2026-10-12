from peewee import CharField, DatabaseProxy, FloatField, IntegerField, Model, TextField

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
    task_id = CharField(null=True)

    class Meta:
        table_name = 'sent_danmaku'
        indexes = (
            (('cid', 'status'), False),
            (('task_id',), False),
        )


class TaskRecord(BaseModel):
    """一条任务的持久记录：身份、描述与运行态。

    只存史实；队列与游标属会话态，另存缓存文件。
    """
    task_id = CharField(primary_key=True)
    bvid = CharField()
    cid = IntegerField()
    video_title = CharField(null=True)
    part_page = IntegerField(null=True)
    part_title = CharField(null=True)
    xml_path = CharField(null=True)
    created_at = FloatField()
    status = CharField()

    class Meta:
        table_name = 'task_record'
        indexes = (
            (('bvid', 'cid'), False),
        )