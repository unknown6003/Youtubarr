from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("youtubarr", "0002_fallbackimportjob"),
    ]

    operations = [
        migrations.CreateModel(
            name="PipelineRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("ok", "OK"), ("failed", "Failed")], default="ok", max_length=16)),
                ("refresh_count", models.IntegerField(default=0)),
                ("normalized_count", models.IntegerField(default=0)),
                ("snapshot_count", models.IntegerField(default=0)),
                ("fallback_count", models.IntegerField(default=0)),
                ("tracks_before", models.IntegerField(default=0)),
                ("tracks_after", models.IntegerField(default=0)),
                ("artists_before", models.IntegerField(default=0)),
                ("artists_after", models.IntegerField(default=0)),
                ("artists_with_mbid_before", models.IntegerField(default=0)),
                ("artists_with_mbid_after", models.IntegerField(default=0)),
                ("latest_payload_count", models.IntegerField(default=0)),
                ("last_error", models.TextField(blank=True, default="")),
            ],
        ),
    ]
