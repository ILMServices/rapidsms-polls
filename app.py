import rapidsms
import datetime

from rapidsms.apps.base import AppBase
from .models import Poll
from django.db.models import Q

class App (AppBase):

    def handle (self, message):
        # see if this contact matches any of our polls
        if (message.connection.contact):
            try:
                poll = Poll.objects.filter(contacts=message.connection.contact).exclude(start_date=None).filter(Q(end_date=None) | (~Q(end_date=None) & Q(end_date__lt=datetime.datetime.now()))).latest('start_date')
                response = poll.process_response(message)    
                message.respond(response)
                return True
            except Poll.DoesNotExist:
                pass

        return False