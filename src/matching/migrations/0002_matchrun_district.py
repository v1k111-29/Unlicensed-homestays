"""One district per match run (D51). No match runs exist before M4, so the table is empty and
no default value is ever applied; the placeholder default only satisfies the operation."""

import django.db.models.deletion
from django.db import migrations, models


def refuse_existing_runs(apps, schema_editor):
    if apps.get_model("matching", "MatchRun").objects.exists():
        raise RuntimeError("match runs exist; assign each a district before this migration")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_seed_districts"),
        ("matching", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(refuse_existing_runs, migrations.RunPython.noop),
        migrations.AddField(
            model_name="matchrun",
            name="district",
            field=models.ForeignKey(
                default=None,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="match_runs",
                to="accounts.district",
            ),
            preserve_default=False,
        ),
    ]
