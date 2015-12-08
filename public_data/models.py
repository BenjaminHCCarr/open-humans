from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.db import models

from common.fields import AutoOneToOneField
from data_import.models import DataRetrievalTask
from open_humans.models import Member


class Participant(models.Model):
    """
    Represents a participant in the Public Data Sharing study.
    """
    member = AutoOneToOneField(Member,
                               related_name='public_data_participant')
    enrolled = models.BooleanField(default=False)
    signature = models.CharField(max_length=70)
    enrollment_date = models.DateTimeField(auto_now_add=True)

    @property
    def public_data(self):
        """
        Return most recent tasks for public sources.

        This is a tuple of (source, DataRetrievalTask) as produced by
        DataRetrievalTask's custom queryset method, "grouped_recent".
        """
        if not self.enrolled:
            return []

        public_sources = [
            a for a in PublicDataAccess.objects.filter(participant=self)
            if a.is_public]
        tasks = (DataRetrievalTask.objects.for_user(self.member.user)
                 .grouped_recent())
        return [t for t in tasks if t[0] in public_sources]

    def __unicode__(self):
        status = 'Enrolled' if self.enrolled else 'Not enrolled'

        return '%s:%s' % (self.member, status)


class PublicDataAccess(models.Model):
    """
    Keep track of public sharing for data source.

    Sources are currently expected to match a study or activity app_label.
    """
    # Max length matches that used for ContentTypes' 'app_label' field.
    participant = models.ForeignKey(Participant)
    data_source = models.CharField(max_length=100)
    is_public = models.BooleanField(default=False)

    def __unicode__(self):
        status = 'Private'

        if self.is_public:
            status = 'Public'

        return '%s:%s:%s' % (self.participant.member.user.username,
                             self.data_source, status)


class PublicDataFileAccess(models.Model):
    """
    Keep track of public sharing for data files.
    data_file_model is expected to be a subclass of data_import.BaseDataFile.
    """
    data_file = GenericForeignKey('data_file_model', 'data_file_id')

    data_file_model = models.ForeignKey(ContentType)
    data_file_id = models.PositiveIntegerField()

    is_public = models.BooleanField(default=False)

    def download_url(self):
        return reverse('public-data:download', args=[self.id])

    def __unicode__(self):
        status = 'Private'

        if self.is_public:
            status = 'Public'

        return '%s:%s' % (self.data_file, status)


class WithdrawalFeedback(models.Model):
    """
    Keep track of any feedback a study participant gives when they withdraw
    from the study.
    """
    member = models.ForeignKey(Member)
    feedback = models.TextField(blank=True)
    withdrawal_date = models.DateTimeField(auto_now_add=True)
