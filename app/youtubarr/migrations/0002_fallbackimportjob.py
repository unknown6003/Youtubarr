from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("youtubarr", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="FallbackImportJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("pending", "Pending"), ("done", "Done"), ("failed", "Failed")], default="pending", max_length=16)),
                ("video_path", models.CharField(blank=True, default="", max_length=1024)),
                ("mp3_path", models.CharField(blank=True, default="", max_length=1024)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("track_item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fallback_jobs", to="youtubarr.trackitem")),
            ],
            options={
                "unique_together": {("track_item",)},
            },
        ),
    ]
