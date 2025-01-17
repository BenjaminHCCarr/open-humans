from __future__ import unicode_literals

import re

from string import digits  # pylint: disable=deprecated-module

import arrow

from autoslug import AutoSlugField

from django.contrib.postgres.fields import ArrayField
from django.db import models, router
from django.db.models.deletion import Collector

from oauth2_provider.models import Application

from common.utils import app_label_to_verbose_name, generate_id
from data_import.models import DataFile
from open_humans.models import Member
from open_humans.storage import PublicStorage

active_help_text = """"Active" status is required to perform authorization
processes, including during drafting stage. If a project is not active, it
won't show up in listings of activities that can be joined by participants, and
new data sharing authorizations cannot occur. Projects which are "active" but
not approved may have some information shared in an "In Development" section,
so Open Humans members can see potential upcoming studies. Removing "active"
status from a project will not remove any uploaded files from a project
member's profile."""

post_sharing_url_help_text = """If provided, after authorizing sharing the
member will be taken to this URL. If this URL includes "PROJECT_MEMBER_ID"
within it, we will replace that with the member's project-specific
project_member_id. This allows you to direct them to an external survey you
operate (e.g. using Google Forms) where a pre-filled project_member_id field
allows you to connect those responses to corresponding data in Open Humans."""


def now_plus_24_hours():
    """
    Return a datetime 24 hours in the future.
    """
    return arrow.utcnow().replace(hours=+24).datetime


def id_label_to_project(id_label):
    """
    Given a project's id_label, return the project.
    """
    match = re.match(r'direct-sharing-(?P<id>\d+)', id_label)

    if match:
        project = DataRequestProject.objects.get(id=int(match.group('id')))
        return project


def app_label_to_verbose_name_including_dynamic(label):
    """
    Given an app's name, return its verbose name.
    """
    try:
        return app_label_to_verbose_name(label)
    except LookupError:
        match = re.match(r'direct-sharing-(?P<id>\d+)', label)

        if match:
            project = DataRequestProject.objects.get(id=int(match.group('id')))

            return project.name


def badge_upload_path(instance, filename):
    """
    Construct the upload path for a project's badge image.
    """
    return 'direct-sharing/badges/{0}/{1}'.format(instance.id, filename)


class DataRequestProject(models.Model):
    """
    Base class for data request projects.

    Some fields are only available to Open Humans admins, including:
        all_sources_access (Boolean): when True, all data sources shared w/proj
        approved (Boolean): when True, member cap is removed and proj is listed
        token_expiration_disabled (Boolean): if True master tokens don't expire
    """

    BOOL_CHOICES = ((True, 'Yes'), (False, 'No'))
    STUDY_CHOICES = ((True, 'Study'), (False, 'Activity'))

    is_study = models.BooleanField(
        choices=STUDY_CHOICES,
        help_text=('A "study" is doing human subjects research and must have '
                   'Institutional Review Board approval or equivalent ethics '
                   'board oversight. Activities can be anything else, e.g. '
                   'data visualizations.'),
        verbose_name='Is this project a study or an activity?')
    name = models.CharField(
        max_length=100,
        verbose_name='Project name')
    slug = AutoSlugField(populate_from='name', unique=True, always_update=True)
    leader = models.CharField(
        max_length=100,
        verbose_name='Leader(s) or principal investigator(s)')
    organization = models.CharField(
        blank=True,
        max_length=100,
        verbose_name='Organization or institution')
    is_academic_or_nonprofit = models.BooleanField(
        choices=BOOL_CHOICES,
        verbose_name=('Is this institution or organization an academic '
                      'institution or non-profit organization?'))
    contact_email = models.EmailField(
        verbose_name='Contact email for your project')
    info_url = models.URLField(
        blank=True,
        verbose_name='URL for general information about your project')
    short_description = models.CharField(
        max_length=140,
        verbose_name='A short description (140 characters max)')
    long_description = models.TextField(
        max_length=1000,
        verbose_name='A long description (1000 characters max)')
    returned_data_description = models.CharField(
        blank=True,
        max_length=140,
        verbose_name=('Description of data you plan to upload to member '
                      ' accounts (140 characters max)'),
        help_text=("Leave this blank if your project doesn't plan to add or "
                   'return new data for your members.'))
    active = models.BooleanField(
        choices=BOOL_CHOICES,
        help_text=active_help_text,
        default=True)
    badge_image = models.ImageField(
        blank=True,
        storage=PublicStorage(),
        upload_to=badge_upload_path,
        max_length=1024,
        help_text=("A badge that will be displayed on the user's profile once "
                   "they've connected your project."))

    request_sources_access = ArrayField(
        models.CharField(max_length=100),
        help_text=('List of sources this project is requesting access to on '
                   'Open Humans.'),
        blank=True,
        default=list,
        verbose_name="Data sources you're requesting access to")
    all_sources_access = models.BooleanField(default=False)

    @property
    def request_sources_access_names(self):
        # pylint: disable=not-an-iterable
        return [app_label_to_verbose_name_including_dynamic(label)
                for label in self.request_sources_access]

    request_message_permission = models.BooleanField(
        choices=BOOL_CHOICES,
        help_text=('Permission to send messages to the member. This does not '
                   'grant access to their email address.'),
        verbose_name='Are you requesting permission to message users?')

    request_username_access = models.BooleanField(
        choices=BOOL_CHOICES,
        help_text=("Access to the member's username. This implicitly enables "
                   'access to anything the user is publicly sharing on Open '
                   'Humans. Note that this is potentially sensitive and/or '
                   'identifying.'),
        verbose_name='Are you requesting Open Humans usernames?')

    coordinator = models.ForeignKey(Member, on_delete=models.PROTECT)
    approved = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    master_access_token = models.CharField(max_length=64, default=generate_id)

    token_expiration_date = models.DateTimeField(default=now_plus_24_hours)
    token_expiration_disabled = models.BooleanField(default=False)

    def __unicode__(self):
        return '{}: {}'.format(self.name, self.coordinator.name)

    def refresh_token(self):
        """
        Generate a new master access token that expires in 24 hours.
        """
        self.master_access_token = generate_id()
        self.token_expiration_date = now_plus_24_hours()

        self.save()

    @property
    def id_label(self):
        return 'direct-sharing-{}'.format(self.id)

    @property
    def project_type(self):
        return 'study' if self.is_study else 'activity'

    @property
    def type(self):
        if hasattr(self, 'oauth2datarequestproject'):
            return 'oauth2'

        if hasattr(self, 'onsitedatarequestproject'):
            return 'on-site'

    @property
    def authorized_members(self):
        return self.project_members.filter_active().count()

    def active_user(self, user):
        return DataRequestProjectMember.objects.get(
            member=user.member,
            project=self,
            joined=True,
            authorized=True,
            revoked=False)

    def is_joined(self, user):
        try:
            self.active_user(user)

            return True
        except DataRequestProjectMember.DoesNotExist:
            return False

    def delete_without_cascade(self, using=None, keep_parents=False):
        """
        Modified version of django's default delete() method.

        This method is added to enable safe deletion of the child models without
        removing objects related to it through the parent. As of Feb 2017,
        no models are directly related to the OAuth2DataRequestProject or
        OnSiteDataRequestProject child models.
        """
        allowed_models = ['private_sharing.onsitedatarequestproject',
                          'private_sharing.oauth2datarequestproject']
        if self._meta.label_lower not in allowed_models:
            raise Exception("'delete_without_cascade' only for child models!")
        using = using or router.db_for_write(self.__class__, instance=self)
        assert self._get_pk_val() is not None, (
            "%s object can't be deleted because its %s attribute is set to None." %
            (self._meta.object_name, self._meta.pk.attname)
        )

        collector = Collector(using=using)
        collector.collect([self], keep_parents=keep_parents,
                          collect_related=False)
        return collector.delete()


class OAuth2DataRequestProject(DataRequestProject):
    """
    Represents a data request project that authorizes through OAuth2.
    """

    class Meta:  # noqa: D101
        verbose_name = 'OAuth2 data request project'

    application = models.OneToOneField(Application)

    enrollment_url = models.URLField(
        help_text=("The URL we direct members to if they're interested in "
                   'sharing data with your project.'),
        verbose_name='Enrollment URL')

    # Note 20170731 MPB: URL is hard-coded below, unfortunately
    # reverse and reverse_lazy can't be used in this case.
    redirect_url = models.CharField(
        max_length=256,
        # TODO: add link
        help_text="""The return URL for our "authorization code" OAuth2 grant
        process. You can <a target="_blank" href="{0}">read more about OAuth2
        "authorization code" transactions here</a>.""".format(
            '/direct-sharing/oauth2-setup/#setup-oauth2-authorization'),
        verbose_name='Redirect URL')

    def save(self, *args, **kwargs):
        if hasattr(self, 'application'):
            application = self.application
        else:
            application = Application()

        application.name = self.name
        application.user = self.coordinator.user
        application.client_type = Application.CLIENT_CONFIDENTIAL
        application.redirect_uris = self.redirect_url
        application.authorization_grant_type = (
            Application.GRANT_AUTHORIZATION_CODE)

        application.save()

        self.application = application

        super(OAuth2DataRequestProject, self).save(*args, **kwargs)


class OnSiteDataRequestProject(DataRequestProject):
    """
    Represents a data request project that authorizes through the Open Humans
    website.
    """

    class Meta:  # noqa: D101
        verbose_name = 'On-site data request project'

    consent_text = models.TextField(
        help_text=('The "informed consent" text that describes your project '
                   'to Open Humans members.'))

    post_sharing_url = models.URLField(
        blank=True,
        verbose_name='Post-sharing URL',
        help_text=post_sharing_url_help_text)


class DataRequestProjectManagerQuerySet(models.QuerySet):
    """
    Add convenience method for getting an active user of the given project.
    """

    def filter_active(self):
        return (self.filter(joined=True, authorized=True, revoked=False)
                .filter(member__user__is_active=True))


class DataRequestProjectMember(models.Model):
    """
    Represents a member's approval of a data request.
    """

    objects = DataRequestProjectManagerQuerySet.as_manager()

    member = models.ForeignKey(Member)
    # represents when a member accepts/authorizes a project
    created = models.DateTimeField(auto_now_add=True)
    project = models.ForeignKey(DataRequestProject,
                                related_name='project_members')
    project_member_id = models.CharField(max_length=16, unique=True)
    message_permission = models.BooleanField(default=False)
    username_shared = models.BooleanField(default=False)
    sources_shared = ArrayField(models.CharField(max_length=100), default=list)
    all_sources_shared = models.BooleanField(default=False)
    consent_text = models.TextField(blank=True)
    joined = models.BooleanField(default=False)
    authorized = models.BooleanField(default=False)
    revoked = models.BooleanField(default=False)

    def __unicode__(self):
        return '{0}:{1}:{2}'.format(repr(self.project),
                                    self.member,
                                    self.project_member_id)

    @property
    def sources_shared_including_self(self):
        return self.sources_shared + [self.project.id_label]

    @staticmethod
    def random_project_member_id():
        """
        Return a zero-padded string 16 digits long that's not already used in
        the database.
        """
        code = generate_id(size=8, chars=digits)

        while DataRequestProjectMember.objects.filter(
                project_member_id=code).count() > 0:
            code = generate_id(size=8, chars=digits)

        return code

    def save(self, *args, **kwargs):
        if not self.project_member_id:
            self.project_member_id = self.random_project_member_id()

        super(DataRequestProjectMember, self).save(*args, **kwargs)


class CompletedManager(models.Manager):
    """
    A manager that only returns completed ProjectDataFiles.
    """

    def get_queryset(self):
        return (super(CompletedManager, self).get_queryset()
                .filter(completed=True))


class ProjectDataFile(DataFile):
    """
    A DataFile specific to DataRequestProjects; these files are linked to a
    project.
    """

    objects = CompletedManager()
    all_objects = models.Manager()

    parent = models.OneToOneField(DataFile,
                                  parent_link=True,
                                  related_name='parent_project_data_file')

    completed = models.BooleanField(default=False)
    direct_sharing_project = models.ForeignKey(DataRequestProject)

    def save(self, *args, **kwargs):
        if not self.source:
            self.source = self.direct_sharing_project.id_label

        super(ProjectDataFile, self).save(*args, **kwargs)


class ActivityFeed(models.Model):
    """
    Holds publicly shareable logs of user activity.

    Because non-project data import activities is a legacy issue, those events
    are not recorded by this model.
    """
    ACTION_CHOICES = (
        ('created-account', 'created-account'),
        ('joined-project', 'joined-project'),
        ('publicly-shared', 'publicly-shared'))

    member = models.ForeignKey(Member)
    project = models.ForeignKey(DataRequestProject, null=True)
    action = models.CharField(ACTION_CHOICES, max_length=15)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.project:
            return '{}:{}:{}'.format(self.member.user.username,
                                     self.action, self.project.slug)
        else:
            return '{}:{}'.format(self.member.user.username, self.action)

    def save(self, *args, **kwargs):
        # Check that project is null only for a project-less action.
        PROJECTLESS_ACTIONS = ['created-account']
        if not self.project and self.action not in PROJECTLESS_ACTIONS:
            raise ValueError('Project required unless action is: {}'.format(
                PROJECTLESS_ACTIONS))
        super(ActivityFeed, self).save(*args, **kwargs)

    @property
    def timedelta(self):
        td = arrow.now() - arrow.get(self.timestamp)
        td_return = {'days': td.days}

        remaining_seconds = td.seconds
        td_return['hours'] = int(remaining_seconds / 3600)
        remaining_seconds -= td_return['hours'] * 3600
        td_return['minutes'] = int(remaining_seconds / 60)
        remaining_seconds -= td_return['hours'] * 60
        td_return['seconds'] = remaining_seconds

        return td_return


class FeaturedProject(models.Model):
    """
    Set up three featured projects for the home page.
    """
    project = models.ForeignKey(DataRequestProject)
    description = models.TextField(blank=True)
