from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from .models import Scheduler, Messages, Receiver
from .tasks import cleanup_expired, schedule_new_messages
from .tasks import calculate_next_send


class SchedulerTesting(TestCase):

    def setUp(self):
        self.now = timezone.now()
        self.later = self.now + timedelta(hours=5)
        self.earlier = self.now - timedelta(hours=5)
        self.almost_night = self.now.replace(hour=19)

    def test_data_insert(self):
        self.recvr1 = Receiver(phone_number = '+16195559088',
                                  first_name = 'gym',
                                  last_name = 'bag',
                                  offset = 0)
        self.recvr1.save()

        self.rcvr_offset1 = Receiver(phone_number = '+18582917032',
                                  first_name = 'junior',
                                  last_name = 'candies',
                                  offset = -7)
        self.rcvr_offset1.save()

        self.rcvr_offset2 = Receiver(phone_number = '+14216341209',
                                  first_name = 'gym',
                                  last_name = 'bag',
                                  offset = 7)
        self.rcvr_offset2.save()

        self.assertTrue(Receiver.objects.filter(
            phone_number='+16195559088').exists())

        self.assertTrue(Receiver.objects.filter(
            phone_number='+18582917032').exists())

        self.assertTrue(Receiver.objects.filter(
            phone_number='+14216341209').exists())


    def test_next_send_calculator(self):
        # Goal: next_send should be in the future
        next_send = calculate_next_send(self.now, interval=False, day=True)
        self.assertLess(self.now, next_send)

        #####################################################################
        # Goal: if day=True, it shouldn't return a time between 8pm and 7am...
        next_send_wInterval = calculate_next_send(self.now, interval=4, day=True)
        next_send_randomInterval = calculate_next_send(self.now, interval=False, day=True)

        # Goal: random or set interval are both set to future
        self.assertLess(self.almost_night, next_send_wInterval)
        self.assertLess(self.almost_night, next_send_randomInterval)

        # Goal: It's not set to an hour after 8pm
        self.assertLess(next_send_wInterval.hour, 20)
        self.assertLess(next_send_randomInterval.hour, 20)

        # Goal: It's not set to an hour before 8am
        self.assertGreaterEqual(next_send_wInterval.hour, 7)
        self.assertGreaterEqual(next_send_randomInterval.hour, 7)

        #############################################################
        # Goal: if you pass in a negative interval,
        # it should return a next_send earlier than this one
        next_send_day_once = calculate_next_send(self.now, interval=-5, day=True)
        next_send_once = calculate_next_send(self.now, interval=-5, day=False)

        self.assertLess(next_send_day_once, self.now)
        self.assertLess(next_send_once, self.now)
        #############################################################

    def test_utc_offset_calculator(self):
        from sms_app.tasks import get_offset_range
        offset1, offset1_allowed = -12, get_offset_range(-9, 13)
        offset2, offset2_allowed = -5, get_offset_range(-5, 13)
        offset3, offset3_allowed = 4, get_offset_range(4, 13)

        ### GOAL: calculator should only return daytime hours, hours
        ### that are "allowed" for that timezone ###
        offset_next_send1 = calculate_next_send(self.now,
                                               UTC_offset = offset1)
        offset_next_send2 = calculate_next_send(self.now,
                                               UTC_offset = offset2)
        offset_next_send3 = calculate_next_send(self.now,
                                               UTC_offset = offset3)

        self.assertTrue(offset_next_send1.hour in offset1_allowed)
        self.assertTrue(offset_next_send2.hour in offset2_allowed)
        self.assertTrue(offset_next_send3.hour in offset3_allowed)
        ##***************************************************##

    def test_scheduler(self):
        recvr1 = Receiver(phone_number = '+16195559088',
                                  first_name = 'gym',
                                  last_name = 'bag',
                                  offset = -8)
        recvr1.save()
        self.assertTrue(Receiver.objects.filter(
            phone_number='+16195559088').exists())

        # One should be scheduled because its stop_time is in the future
        self.test_msg_one = Messages(init_schedule_time = self.now,
                            send_only_during_daytime = True,
                            stop_time = self.later,
                            send_is_on = True)
        self.test_msg_one.save()

        # Two should /not/ be scheduled because its stop time is in the past
        self.test_msg_two = Messages(init_schedule_time = self.now,
                    send_only_during_daytime = True,
                    stop_time = self.earlier,
                    send_is_on = True)
        self.test_msg_two.save()

        # Three should be scheduled and then have a next_send_time in the past
        # because three has the attribute send_once set to True
        self.test_msg_three = Messages(init_schedule_time = self.now,
                    send_only_during_daytime = True,
                    stop_time = self.later,
                    send_once = True,
                    send_is_on = True)
        self.test_msg_three.save()

        self.test_msg_one.recipients.add(recvr1)
        self.test_msg_two.recipients.add(recvr1)
        self.test_msg_three.recipients.add(recvr1)

        self.test_msg_one.save()
        self.test_msg_two.save()
        self.test_msg_three.save()

        schedule_new_messages() # should insert one and three.
        self.assertTrue(Scheduler.objects.filter(message_id=self.test_msg_one).exists())
        self.assertTrue(Scheduler.objects.filter(message_id=self.test_msg_three).exists())

        # should not insert second message where stop time is earlier than now
        self.assertFalse(Scheduler.objects.filter(message_id=self.test_msg_two).exists())

        # the third message should have a next_send set to the past
        scheduled_three = Scheduler.objects.get(message_id=self.test_msg_three)
        self.assertLess(scheduled_three.next_send, self.now)


# class CleanupTesting(TestCase):

#     def test_cleanup(self):
#         self.recvr1 = Receiver(phone_number = '+16195559088',
#                                   first_name = 'gym',
#                                   last_name = 'bag',
#                                   offset = -8)
#         self.recvr1.save()

#         # Build a test-message where send_true and msg.stop_time is in the past
#         # 1a)  Manually put this message in the scheduler
#         # Goals: on cleanup make sure it a) is deleted from schedule,
#         # and b) that msg.send_is_on is set to false
#         self.now = timezone.now()
#         self.earlier = self.now - timedelta(hours = 8)
#         self.later = self.now + timedelta(hours = 8)
        
#         test_msg_clean = Messages(init_schedule_time = self.now,
#                             send_only_during_daytime = True,
#                             stop_time = self.later,
#                             send_is_on = True)
#         test_msg_clean.save()
#         test_msg_clean.recipients.add(self.recvr1)
#         test_msg_clean.save()

#         schedule_new_messages()
#         self.assertTrue(Scheduler.objects.filter(message_id=test_msg_clean).exists())

#         test_msg_clean.stop_time = self.earlier
#         test_msg_clean.save()

#         cleanup_expired()

#         if test_msg_clean.send_is_on is True:
#             self.fail("Message is still set to send")

#         with self.assertRaises(Scheduler.DoesNotExist):
#             Scheduler.objects.get(message_id=test_msg_clean).exists()

# class SenderTesting(TestCase):
#     pass
