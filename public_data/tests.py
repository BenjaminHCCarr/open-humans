from django.contrib.auth import get_user_model
from django.test import TestCase

from common.testing import SmokeTestCase
from common.utils import get_source_labels
from open_humans.models import Member

from .models import Participant, PublicDataAccess

UserModel = get_user_model()


class PublicDataTestCase(TestCase):
    """
    Tests for handling of public data.
    """

    def setUp(self):  # noqa
        user = UserModel.objects.create(username='test-user')
        member = Member.objects.create(user=user)

        participant = Participant.objects.create(member=member, enrolled=True)

        PublicDataAccess.objects.create(
            participant=participant,
            data_source=get_source_labels()[0],
            is_public=True)

    def test_withdrawing_should_set_data_files_to_private(self):
        user = UserModel.objects.get(username='test-user')

        self.assertTrue(user.member.public_data_participant.enrolled)
        self.assertTrue(user.member.public_data_participant
                        .publicdataaccess_set.all()[0].is_public)

        user.member.public_data_participant.enrolled = False
        user.member.public_data_participant.save()

        self.assertFalse(user.member.public_data_participant.enrolled)
        self.assertFalse(user.member.public_data_participant
                         .publicdataaccess_set.all()[0].is_public)


class SmokeTests(SmokeTestCase):
    """
    A simple GET test for all of the simple URLs in the site.
    """

    authenticated_or_anonymous_urls = [
        '/public-data/',
        '/public-data/consent/',
    ]

    authenticated_urls = [
        '/public-data/enroll-1-overview/',
        '/public-data/enroll-2-information/',
        '/public-data/toggle-sharing/',
        '/public-data/withdraw/',
    ]

    post_only_urls = [
        '/public-data/enroll-3-quiz/',
        '/public-data/enroll-4-signature/',
    ]
