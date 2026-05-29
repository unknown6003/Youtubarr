from django.db import migrations, models


def mark_incomplete_runs_running(apps, schema_editor):
    PipelineRun = apps.get_model("youtubarr", "PipelineRun")
    PipelineRun.objects.filter(finished_at__isnull=True).update(status="running")


class Migration(migrations.Migration):
    dependencies = [
        ("youtubarr", "0003_pipelinerun"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pipelinerun",
            name="status",
            field=models.CharField(choices=[("ok", "OK"), ("failed", "Failed"), ("running", "Running")], default="running", max_length=16),
        ),
        migrations.RunPython(mark_incomplete_runs_running, migrations.RunPython.noop),
    ]
