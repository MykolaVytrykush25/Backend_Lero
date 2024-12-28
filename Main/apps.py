from django.apps import AppConfig


class MainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Main'
    def ready(self):
        self.setup_periodic_task()

    @staticmethod
    def setup_periodic_task():
        from celery import current_app
        from django_celery_beat.models import PeriodicTask, CrontabSchedule

        if not current_app:
            return

        try:
            schedule, created = CrontabSchedule.objects.get_or_create(
                minute='00',
                hour='00',
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
                timezone='UTC'
            )

            PeriodicTask.objects.get_or_create(
                crontab=schedule,
                name='Prolong Main Proxy Plan',
                defaults={'task': "prolong_main_proxy_plan"},
            )

            if created:
                print('Периодическая задача создана.')
            else:
                print('Периодическая задача уже существует.')

        except Exception as e:
            print(f'Ошибка при настройке периодической задачи: {e}')
