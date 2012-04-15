#!/usr/bin/env python
import logging
logger = logging.getLogger('')

from time import sleep

from django.conf import settings

from operations import operations
from models import Task

def run_downloader():
    def loop():
        while True:
            for task in Task.objects.all():
                if task.function in operations.keys():
                    logger.info(" [x] Received %r, processing..." % (task,))
                    operations[task.function](*task.args)
                    logger.info(" [x] End, waiting for next event")
                else:
                    logger.warn(" /!\ unknow signal: %s" % task)
                task.delete()
            sleep(3)

    settings.CACHE_SCRAPING = False

    # clean task list before starting
    Task.objects.all().delete()

    logging.info(' [*] Waiting for events. To exit press CTRL+C')

    try:
        loop()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    run_downloader()