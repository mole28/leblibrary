from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0003_alter_torahtext_book_alter_torahtext_chapter_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContactMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, verbose_name='שם')),
                ('phone', models.CharField(blank=True, max_length=40, verbose_name='טלפון')),
                ('email', models.CharField(blank=True, max_length=254, verbose_name='אימייל')),
                ('subject', models.CharField(max_length=200, verbose_name='נושא')),
                ('message', models.TextField(verbose_name='תוכן ההודעה')),
                ('email_sent', models.BooleanField(default=False, verbose_name='התראה נשלחה במייל')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='תאריך פנייה')),
            ],
            options={
                'verbose_name': 'פניית גולש',
                'verbose_name_plural': 'פניות גולשים',
                'ordering': ['-created_at'],
            },
        ),
    ]