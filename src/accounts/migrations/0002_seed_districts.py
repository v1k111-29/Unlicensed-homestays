"""Seed the 8 project districts (D18). Real district names (public place names, not personal
data). Tamil names are machine-written and need native review (Q3)."""

from django.db import migrations

DISTRICTS = [
    ("Nilgiris", "நீலகிரி"),
    ("Coimbatore", "கோயம்புத்தூர்"),
    ("Madurai", "மதுரை"),
    ("Dindigul", "திண்டுக்கல்"),
    ("Kanyakumari", "கன்னியாகுமரி"),
    ("Thanjavur", "தஞ்சாவூர்"),
    ("Ramanathapuram", "இராமநாதபுரம்"),
    ("Chennai", "சென்னை"),
]


def seed(apps, schema_editor):
    District = apps.get_model("accounts", "District")
    for name_en, name_ta in DISTRICTS:
        District.objects.get_or_create(name_en=name_en, defaults={"name_ta": name_ta})


def unseed(apps, schema_editor):
    District = apps.get_model("accounts", "District")
    District.objects.filter(name_en__in=[d[0] for d in DISTRICTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
