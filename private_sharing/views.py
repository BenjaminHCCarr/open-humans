from collections import OrderedDict

from django.conf import settings
from django.contrib import messages as django_messages
from django.core.urlresolvers import reverse, reverse_lazy
from django.http import Http404, HttpResponseRedirect
from django.views.generic import (CreateView, DetailView, FormView,
                                  TemplateView, UpdateView, View)

from oauth2_provider.models import AccessToken, RefreshToken

from common.activities import (data_request_project_badge,
                               personalize_activities_dict)
from common.mixins import LargePanelMixin, PrivateMixin
from common.views import BaseOAuth2AuthorizationView

# TODO: move this to common
from open_humans.mixins import SourcesContextMixin
from private_sharing.models import ActivityFeed

from .forms import (MessageProjectMembersForm, OAuth2DataRequestProjectForm,
                    OnSiteDataRequestProjectForm)
from .models import (DataRequestProject, DataRequestProjectMember,
                     OAuth2DataRequestProject, OnSiteDataRequestProject)

from data_import.models import DataFile

MAX_UNAPPROVED_MEMBERS = settings.MAX_UNAPPROVED_MEMBERS


class CoordinatorOrActiveMixin(object):
    """
    - Always let the coordinator view this page
    - Only let members view it if the project is active
    - Only let members view it if the project is not approved and less than
      MAX_UNAPPROVED_MEMBERS have joined.
    """

    def dispatch(self, *args, **kwargs):
        project = self.get_object()

        if project.coordinator == self.request.user:
            return super(CoordinatorOrActiveMixin, self).dispatch(
                *args, **kwargs)

        if not project.active:
            raise Http404

        if (not project.approved and
                project.authorized_members > MAX_UNAPPROVED_MEMBERS):
            django_messages.error(self.request, (
                """Sorry, "{}" has not been approved and has exceeded the {}
                member limit for unapproved projects.""".format(
                    project.name, MAX_UNAPPROVED_MEMBERS)))

            return HttpResponseRedirect(reverse('my-member-data'))

        return super(CoordinatorOrActiveMixin, self).dispatch(
            *args, **kwargs)


class ProjectMemberMixin(object):
    """
    Add project_member and related helper methods.
    """

    @property
    def project_member(self):
        project = self.get_object()

        project_member, _ = DataRequestProjectMember.objects.get_or_create(
            member=self.request.member,
            project=project)

        return project_member

    @property
    def project_joined_by_member(self):
        return self.project_member and self.project_member.joined

    @property
    def project_authorized_by_member(self):
        return self.project_member and self.project_member.authorized

    def authorize_member(self):
        project = self.get_object()

        self.request.user.log('direct-sharing:{0}:authorize'.format(
            project.type), {'project-id': project.id})

        django_messages.success(self.request, (
            'You have successfully joined the project "{}".'.format(
                project.name)))
        if project.approved:
            event = ActivityFeed(
                member=self.project_member.member,
                project=project,
                action='joined-project')
            event.save()

        project_member = self.project_member

        # The OAuth2 projects have join and authorize in the same step
        if project.type == 'oauth2':
            project_member.joined = True

        project_member.authorized = True
        project_member.revoked = False
        project_member.message_permission = project.request_message_permission
        project_member.username_shared = project.request_username_access
        project_member.sources_shared = project.request_sources_access
        project_member.all_sources_shared = project.all_sources_access

        project_member.save()


class OnSiteDetailView(ProjectMemberMixin, CoordinatorOrActiveMixin,
                       DetailView):
    """
    A base DetailView for on-site projects.
    """

    model = OnSiteDataRequestProject


class JoinOnSiteDataRequestProjectView(PrivateMixin, LargePanelMixin,
                                       OnSiteDetailView):
    """
    Display the consent form for a project.
    """

    template_name = 'private_sharing/join-on-site.html'

    def dispatch(self, *args, **kwargs):
        """
        If the member has already accepted the consent form redirect them to
        the authorize page.
        """
        if self.project_joined_by_member:
            return HttpResponseRedirect(reverse_lazy(
                'direct-sharing:authorize-on-site',
                kwargs={'slug': self.get_object().slug}))

        return super(JoinOnSiteDataRequestProjectView, self).dispatch(
            *args, **kwargs)

    # pylint: disable=unused-argument
    def post(self, request, *args, **kwargs):
        project = self.get_object()
        project_member = self.project_member

        project_member.joined = True

        # store the consent text that the user has consented to
        project_member.consent_text = project.consent_text

        # if the user joins again after revoking the study then reset their
        # revoked and authorized status
        project_member.revoked = False
        project_member.authorized = False

        project_member.save()

        request.user.log('direct-sharing:on-site:consent', {
            'project-id': project.id
        })

        return HttpResponseRedirect(
            reverse_lazy('direct-sharing:authorize-on-site',
                         kwargs={'slug': project.slug}))


class ConnectedSourcesMixin(object):
    """
    Add context for connected/unconnected sources.
    """

    def get_context_data(self, **kwargs):
        context = super(ConnectedSourcesMixin, self).get_context_data(**kwargs)

        project = self.get_object()
        activities = personalize_activities_dict(self.request.user)

        context.update({
            'project_authorized_by_member': self.project_authorized_by_member,
            'sources': OrderedDict([
                (source_name, activities[source_name]['is_connected'])
                for source_name in project.request_sources_access
                if source_name in activities
            ])
        })

        return context


class AuthorizeOnSiteDataRequestProjectView(PrivateMixin, LargePanelMixin,
                                            ConnectedSourcesMixin,
                                            OnSiteDetailView):
    """
    Display the requested permissions for a project.
    """

    template_name = 'private_sharing/authorize-on-site.html'

    def dispatch(self, *args, **kwargs):
        """
        If the member hasn't already accepted the consent form redirect them to
        the consent form page.
        """
        # the opposite of the test in the join page
        if not self.project_joined_by_member:
            return HttpResponseRedirect(reverse_lazy(
                'direct-sharing:join-on-site',
                kwargs={'slug': self.get_object().slug}))

        return super(AuthorizeOnSiteDataRequestProjectView, self).dispatch(
            *args, **kwargs)

    # pylint: disable=unused-argument
    def post(self, request, *args, **kwargs):
        if self.request.POST.get('cancel') == 'cancel':
            self.project_member.delete()

            return HttpResponseRedirect(reverse('home'))

        self.authorize_member()

        project = self.get_object()

        if project.post_sharing_url:
            redirect_url = project.post_sharing_url.replace(
                'PROJECT_MEMBER_ID',
                self.project_member.project_member_id)
        else:
            redirect_url = reverse('activity-management',
                                   kwargs={'source': project.slug})

        return HttpResponseRedirect(redirect_url)

    def get_context_data(self, **kwargs):
        context = super(AuthorizeOnSiteDataRequestProjectView,
                        self).get_context_data(**kwargs)

        project_badge = data_request_project_badge(self.get_object())

        context.update({
            'project_badge': project_badge,
            'activities': personalize_activities_dict(self.request.user),
            'username': self.request.user.username,
        })

        return context


class AuthorizeOAuth2ProjectView(ConnectedSourcesMixin, ProjectMemberMixin,
                                 BaseOAuth2AuthorizationView):
    """
    Override oauth2_provider view to add origin, context, and customize login
    prompt.
    """

    template_name = 'private_sharing/authorize-oauth2.html'

    def dispatch(self, *args, **kwargs):
        if not self.application.oauth2datarequestproject:
            raise Http404

        return super(AuthorizeOAuth2ProjectView, self).dispatch(
            *args, **kwargs)

    def get_object(self):
        return self.application.oauth2datarequestproject

    def form_valid(self, form):
        """
        Override the OAuth2 AuthorizationView's form_valid to authorize a
        project member if the user authorizes the OAuth2 request.
        """
        allow = form.cleaned_data.get('allow')

        if allow:
            self.authorize_member()

        return super(AuthorizeOAuth2ProjectView, self).form_valid(form)

    def get_context_data(self, **kwargs):
        context = super(AuthorizeOAuth2ProjectView,
                        self).get_context_data(**kwargs)

        project_badge = data_request_project_badge(self.get_object())

        context.update({
            'object': self.get_object(),
            'project_badge': project_badge,
            'activities': personalize_activities_dict(self.request.user),
            # XXX: BaseOAuth2AuthorizationView doesn't provide the request
            # context for some reason
            'request': self.request,
            'username': self.request.user.username,
        })

        return context


class CoordinatorOnlyView(View):
    """
    Only let coordinators and superusers view these pages.
    """

    def dispatch(self, *args, **kwargs):
        self.object = self.get_object()

        if self.object.coordinator.user != self.request.user:
            if not self.request.user.is_superuser:
                raise Http404

        return super(CoordinatorOnlyView, self).dispatch(*args, **kwargs)


class UpdateDataRequestProjectView(PrivateMixin, LargePanelMixin, CoordinatorOnlyView, UpdateView):
    """
    Base view for creating an data request activities.
    """

    success_url = reverse_lazy('direct-sharing:manage-projects')


class CreateDataRequestProjectView(PrivateMixin, LargePanelMixin, CreateView):
    """
    Base view for creating an data request activities.
    """

    success_url = reverse_lazy('direct-sharing:manage-projects')

    def form_valid(self, form):
        """
        If the form is valid, redirect to the supplied URL.
        """
        form.instance.coordinator = self.request.member

        return super(CreateDataRequestProjectView, self).form_valid(form)


class CreateOAuth2DataRequestProjectView(CreateDataRequestProjectView):
    """
    Create an OAuth2DataRequestProject.
    """

    template_name = 'private_sharing/create-project.html'
    model = OAuth2DataRequestProject
    form_class = OAuth2DataRequestProjectForm


class CreateOnSiteDataRequestProjectView(CreateDataRequestProjectView):
    """
    Create an OnSiteDataRequestProject.
    """

    template_name = 'private_sharing/create-project.html'
    model = OnSiteDataRequestProject
    form_class = OnSiteDataRequestProjectForm


class UpdateOAuth2DataRequestProjectView(UpdateDataRequestProjectView):
    """
    Update an OAuth2DataRequestProject.
    """

    template_name = 'private_sharing/update-project.html'
    model = OAuth2DataRequestProject
    form_class = OAuth2DataRequestProjectForm


class UpdateOnSiteDataRequestProjectView(UpdateDataRequestProjectView):
    """
    Update an OnSiteDataRequestProject.
    """

    template_name = 'private_sharing/update-project.html'
    model = OnSiteDataRequestProject
    form_class = OnSiteDataRequestProjectForm


class RefreshTokenMixin(object):
    """
    A mixin that adds a POST handler for refreshing a project's token.
    """

    # pylint: disable=unused-argument
    def post(self, request, *args, **kwargs):
        if self.request.POST.get('refresh_token') == 'refresh_token':
            self.object.refresh_token()

        return self.get(request, *args, **kwargs)


class OAuth2DataRequestProjectDetailView(PrivateMixin, CoordinatorOnlyView,
                                         RefreshTokenMixin, DetailView):
    """
    Display an OAuth2DataRequestProject.
    """

    template_name = 'private_sharing/project-detail.html'
    model = OAuth2DataRequestProject


class OnSiteDataRequestProjectDetailView(PrivateMixin, CoordinatorOnlyView,
                                         RefreshTokenMixin, DetailView):
    """
    Display an OnSiteDataRequestProject.
    """

    template_name = 'private_sharing/project-detail.html'
    model = OnSiteDataRequestProject


class ManageDataRequestActivitiesView(PrivateMixin, TemplateView):
    """
    A view for listing all data request activities for the current user.
    """

    template_name = 'private_sharing/manage.html'

    def get_context_data(self, **kwargs):
        context = super(ManageDataRequestActivitiesView,
                        self).get_context_data(**kwargs)

        query = {'coordinator__user': self.request.user}

        oauth2 = OAuth2DataRequestProject.objects.filter(**query)
        onsite = OnSiteDataRequestProject.objects.filter(**query)

        context.update({
            'onsite': onsite,
            'oauth2': oauth2,
        })

        return context


class InDevelopmentView(TemplateView):
    """
    Add in-development projects to template context.
    """

    template_name = 'private_sharing/in-development.html'

    def get_context_data(self, **kwargs):
        context = super(InDevelopmentView, self).get_context_data(**kwargs)

        context.update({
            'projects': DataRequestProject.objects.filter(
                approved=False, active=True)
        })

        return context


class OverviewView(SourcesContextMixin, TemplateView):
    """
    Add current sources to template context.
    """

    template_name = 'direct-sharing/overview.html'


class ProjectLeaveView(PrivateMixin, DetailView):
    """
    Let a member remove themselves from a project.
    """

    template_name = 'private_sharing/leave-project.html'
    model = DataRequestProjectMember

    # pylint: disable=unused-argument
    def post(self, *args, **kwargs):
        project_member = self.get_object()
        project_member.revoked = True
        project_member.joined = False
        project_member.authorized = False
        project_member.save()

        if project_member.project.type == 'oauth2':
            application = (project_member.project
                           .oauth2datarequestproject.application)

            AccessToken.objects.filter(
                user=project_member.member.user,
                application=application).delete()

            RefreshToken.objects.filter(
                user=project_member.member.user,
                application=application).delete()

        self.request.user.log(
            'direct-sharing:{0}:revoke'.format(
                project_member.project.type),
            {'project-id': project_member.id})

        if self.request.POST.get('remove_datafiles', 'off') == 'on':
            DataFile.objects.filter(user=self.request.user,
                                    source=project_member.project
                                    .id_label).delete()

        if 'next' in self.request.GET:
            return HttpResponseRedirect(self.request.GET['next'])
        else:
            return HttpResponseRedirect(reverse('my-member-connections'))


class MessageProjectMembersView(PrivateMixin, CoordinatorOnlyView, DetailView,
                                FormView):
    """
    A view for coordinators to message their project members.
    """

    form_class = MessageProjectMembersForm
    model = DataRequestProject
    template_name = 'private_sharing/message-project-members.html'

    def get_success_url(self):
        project = self.get_object()

        return reverse_lazy('direct-sharing:detail-{}'.format(project.type),
                            kwargs={'slug': project.slug})

    def form_valid(self, form):
        form.send_messages(self.get_object())

        django_messages.success(self.request,
                                'Your message was sent successfully.')

        return super(MessageProjectMembersView, self).form_valid(form)
