from django.db import migrations, models


def copy_from_game(apps, schema_editor):
    """이미 세트에 연결된 영상은 그 세트의 op.gg 경기 번호·세트 번호를 옮겨 둔다."""
    GameVideo = apps.get_model("matches", "GameVideo")
    for v in GameVideo.objects.exclude(game=None).select_related("game__match"):
        v.opgg_match, v.set_number = v.game.match.opgg_id, v.game.number
        v.save(update_fields=["opgg_match", "set_number"])


class Migration(migrations.Migration):
    dependencies = [("matches", "0006_game_bans_video_header")]

    operations = [
        migrations.AddField(model_name="gamevideo", name="opgg_match",
                            field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="gamevideo", name="set_number",
                            field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.RunPython(copy_from_game, migrations.RunPython.noop),
    ]
