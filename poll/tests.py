from django.test import TestCase
from poll.models import STARTSWITH_PATTERN_TEMPLATE
import re

from datetime import datetime
from django.contrib.auth.models import User
from django.db.models import Manager
from django.conf import settings

from rapidsms.models import Contact, Connection, Backend
from rapidsms.tests.scripted import TestScript
from poll.models import Poll, Response, Category, Rule
from rapidsms_httprouter.router import get_router
from rapidsms_httprouter.models import Message
from rapidsms_httprouter.managers import ForUpdateManager
from eav.models import Attribute

from django.db.models.signals import post_save

class BasicPatternTemplateTest(TestCase):
    def test_basic_pattern_template(self):
        testregex = (STARTSWITH_PATTERN_TEMPLATE % '|'.join(['my', 'three', 'keywords']))

        rx = re.compile(testregex)
        self.failIf(not rx.search('my'))
        self.failIf(not rx.search(' my'))
        self.failIf(not rx.search('my '))
        self.failIf(not rx.search('three'))
        self.failIf(not rx.search('keywords'))
        self.failIf(not rx.search('my1'))
        self.failIf(not rx.search('my1. some more text'))
        self.failIf(rx.search('some text and then i say my'))
        self.failIf(rx.search('some text and then i say my '))
        self.failIf(rx.search('myopic'))

class TestScript(TestCase):

    def fake_incoming(self,connection, incoming_message):
        router = get_router()
        return router.handle_incoming(connection.backend.name, connection.identity, incoming_message)


    def assertInteraction(self, connection, incoming_message, expected_response):
        incoming_obj = self.fake_incoming(connection, incoming_message)
        self.assertEquals(Message.objects.filter(in_response_to=incoming_obj, text=expected_response).count(), 1)


class ProcessingTests(TestScript):

    #def tearDown(self):
    #    settings.ROUTER_URL = self.old_router_url

    def setUp(self):
        #self.old_router_url = settings.ROUTER_URL
        #settings.ROUTER_URL = None

        self.user,created = User.objects.get_or_create(username='admin')

        self.backend = Backend.objects.create(name='test')

        self.contact1 = Contact.objects.create(name='John Jonny')
        self.connection1 = Connection.objects.create(backend=self.backend, identity='8675309', contact=self.contact1)

        self.contact2 = Contact.objects.create(name='Test McTesterton')
        self.connection2 = Connection.objects.create(backend=self.backend, identity='5555555', contact=self.contact2)

    def test_simple_poll_responses(self):
        p = Poll.create_with_bulk(
                'test poll1',
                Poll.TYPE_TEXT,
                'test?',
                'test!',
                [self.contact1],
                self.user)
        p.start()
        # starting a poll should send out a message
        self.assertEquals(Message.objects.count(), 1)
        self.assertEquals(Message.objects.all()[0].text, 'test?')

        self.assertInteraction(self.connection1, "test poll response", "test!")
        self.assertEqual(Response.objects.count(), 1)
        self.assertEqual(Response.objects.all()[0].eav.poll_text_value, 'test poll response')

        p2 = Poll.create_with_bulk(
                'test poll2',
                 Poll.TYPE_NUMERIC,
                 'test?',
                 '#test!',
                 [self.contact2],
                 self.user)
        p2.start()

        self.assertInteraction(self.connection2, '3.1415', '#test!')
        self.assertEqual(Response.objects.count(), 2)
        # There should only be one response for a numeric type poll, 
        # and it should have the value
        # we just sent in
        self.assertEqual(Response.objects.filter(poll__type=Poll.TYPE_NUMERIC)[0].eav.poll_number_value, 3.1415)

    def test_yes_no_polls(self):
        p = Poll.create_with_bulk(
                'test poll1',
                Poll.TYPE_TEXT,
                'are you there?',
                'glad to know where you are!',
                [self.contact1, self.contact2],
                self.user)
        p.add_yesno_categories()
        p.start()
        self.assertInteraction(self.connection2, 'yes', 'glad to know where you are!')
        self.assertEqual(Response.objects.filter(poll=p).count(), 1)
        self.assertEqual(Response.objects.get(poll=p).categories.all()[0].category.name, 'yes')

    def test_numeric_polls(self):
        p = Poll.create_with_bulk(
                'test poll numeric',
                Poll.TYPE_NUMERIC,
                'how old are you?',
                ':) go yo age!',
                [self.contact1, self.contact2],
                self.user)
        p.start()
        self.assertInteraction(self.connection2, '19years', ':) go yo age!')
        self.assertEqual(Response.objects.filter(poll=p).count(), 1)

    def test_recategorization(self):
        p = Poll.create_with_bulk(
                'test poll1',
                Poll.TYPE_TEXT,
                'whats your favorite food?',
                'thanks!',
                [self.contact1, self.contact2],
                self.user)
        p.start()
        self.assertInteraction(self.connection1, 'apples', 'thanks!')
        r1 = Response.objects.all()[0]
        self.assertInteraction(self.connection2, 'oranges', 'thanks!')
        r2 = Response.objects.order_by('-pk')[0]
        self.assertInteraction(self.connection1, 'pizza', 'thanks!')
        r3 = Response.objects.order_by('-pk')[0]
        self.assertInteraction(self.connection2, 'pringles', 'thanks!')
        r4 = Response.objects.order_by('-pk')[0]
        self.assertInteraction(self.connection1, 'steak', 'thanks!')
        r5 = Response.objects.order_by('-pk')[0]
        self.assertInteraction(self.connection2, 'pork chop', 'thanks!')
        r6 = Response.objects.order_by('-pk')[0]
        self.assertInteraction(self.connection2, 'moldy bread', 'thanks!')
        r7 = Response.objects.order_by('-pk')[0]

        for r in Response.objects.all():
            self.assertEqual(r.categories.count(), 0)

        for name, keywords in [('healthy', ['apples', 'oranges']),
                                   ('junk', ['pizza', 'pringles']),
                                   ('meaty', ['steak', 'pork'])]:
            category = Category.objects.create(name=name, poll=p)
            for keyword in keywords:
                r = Rule.objects.create(category=category, rule_type=Rule.TYPE_CONTAINS, rule_string=keyword)
                r.update_regex()
                r.save()

        p.reprocess_responses()

        for r, c in [(r1, 'healthy'), (r2, 'healthy'), (r3, 'junk'), (r4, 'junk'), (r5, 'meaty'), (r6, 'meaty')]:
            self.assertEqual(r.categories.count(), 1)
            self.assertEqual(r.categories.all()[0].category.name, c)

        self.assertEquals(r7.categories.count(), 0)
    def test_response_type_handling(self):
        #test allow all
        poll1 = Poll.create_with_bulk(
                'test response type handling',
                Poll.TYPE_TEXT,
                'ureport is bored.what would u like it 2 do?',
                'yikes :(',
                [self.contact1, self.contact2],
                self.user)
        poll1.start()
        self.assertInteraction(self.connection1, 'get me a kindle :)', 'yikes :(')
        self.assertInteraction(self.connection1, 'get me a kindle :)', 'yikes :(')
        self.assertInteraction(self.connection1, 'get me an ipad :)', 'yikes :(')
        self.assertInteraction(self.connection1, 'Arrest Bush :)', 'yikes :(')
        self.assertEqual(Response.objects.filter(contact=self.contact1).count(), 4)
        poll1.end()


        #test ignore dups
        poll2 = Poll.create_with_bulk(
                'test response type handling',
                Poll.TYPE_TEXT,
                'ureport is bored.what would u like it 2 do?',
                'yikes :(',
                [self.contact1, self.contact2],
                self.user)
        poll2.response_type=Poll.RESPONSE_TYPE_NO_DUPS
        poll2.save()

        poll2.start()
        self.assertInteraction(self.connection1, 'get me a kindle :)', 'yikes :(')
        self.fake_incoming(self.connection1, 'get me a kindle :)')
        self.assertInteraction(self.connection1, 'get me an ipad :)', 'yikes :(')
        self.assertInteraction(self.connection1, 'Arrest Bush :)', 'yikes :(')
        self.assertEqual(Response.objects.filter(contact=self.contact1,poll=poll2).count(), 3)
        poll2.end()
        #test allow one

        poll3 = Poll.create_with_bulk(
                'test response type handling',
                Poll.TYPE_TEXT,
                'ureport is bored.what would u like it 2 do?',
                'yikes :(',
                [self.contact1, self.contact2],
                self.user)
        poll3.response_type=Poll.RESPONSE_TYPE_ONE
        poll3.save()
        poll3.start()
        self.assertInteraction(self.connection1, 'get me a kindle :)', 'yikes :(')
        self.fake_incoming(self.connection1, 'get me a kindle :)')
        self.fake_incoming(self.connection1, 'get me an ipad :)')
        self.fake_incoming(self.connection1, 'Arrest Bush :)')
        self.assertEqual(Response.objects.filter(contact=self.contact1,poll=poll3).count(), 1)
