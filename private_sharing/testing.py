from cStringIO import StringIO

from common.testing import SmokeTestCase

from .models import DataRequestProjectMember, ProjectDataFile


class DirectSharingMixin(object):
    """
    Mixins for both types of direct sharing tests.
    """

    fixtures = SmokeTestCase.fixtures + [
        'private_sharing/fixtures/test-data.json',
    ]

    @staticmethod
    def setUp():
        """
        Delete all ProjectMembers so tests don't rely on each others' state.
        """
        DataRequestProjectMember.objects.all().delete()

    def update_member(self, joined, authorized, revoked=False):
        # first delete the ProjectMember
        try:
            project_member = DataRequestProjectMember.objects.get(
                member=self.member1,
                project=self.member1_project)

            project_member.delete()
        except DataRequestProjectMember.DoesNotExist:
            pass

        # then re-create it
        project_member = DataRequestProjectMember(
            member=self.member1,
            project=self.member1_project,
            joined=joined,
            authorized=authorized,
            revoked=revoked,
            sources_shared=self.member1_project.request_sources_access,
            all_sources_shared=self.member1_project.all_sources_access,
            username_shared=self.member1_project.request_username_access,
            message_permission=self.member1_project.request_message_permission)

        project_member.save()

        return project_member


class DirectSharingTestsMixin(object):

    def test_file_upload(self):
        member = self.update_member(joined=True, authorized=True)

        response = self.client.post(
            '/api/direct-sharing/project/files/upload/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={
                'project_member_id': member.project_member_id,
                'metadata': ('{"description": "Test description...", '
                             '"tags": ["tag 1", "tag 2", "tag 3"]}'),
                'data_file': StringIO('just testing...'),
            })

        response_json = response.json()

        self.assertIn('id', response_json)
        self.assertEqual(response.status_code, 201)
        self.assertNotIn('errors', response_json)

        data_file = ProjectDataFile.objects.get(
            id=response_json['id'],
            direct_sharing_project=self.member1_project,
            user=self.member1.user)

        self.assertEqual(data_file.metadata['description'],
                         'Test description...')

        self.assertEqual(data_file.metadata['tags'],
                         ['tag 1', 'tag 2', 'tag 3'])

        self.assertEqual(data_file.file.readlines(), ['just testing...'])

    def test_file_upload_bad_metadata(self):
        member = self.update_member(joined=True, authorized=True)

        # tags not an array
        response = self.client.post(
            '/api/direct-sharing/project/files/upload/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={
                'project_member_id': member.project_member_id,
                'metadata': ('{"description": "Test description...", '
                             '"tags": "tag 1, tag 2, tag 3"}'),
                'data_file': StringIO('just testing...'),
            })

        json = response.json()

        self.assertIn('metadata', json)
        self.assertEqual(json['metadata'],
                         ['"tags" must be an array of strings'])
        self.assertEqual(response.status_code, 400)

        # tags missing
        response = self.client.post(
            '/api/direct-sharing/project/files/upload/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={
                'project_member_id': member.project_member_id,
                'metadata': '{"description": "Test description..."}',
                'data_file': StringIO('just testing...'),
            })

        json = response.json()

        self.assertIn('metadata', json)
        self.assertEqual(response.status_code, 400)

        # description missing
        response = self.client.post(
            '/api/direct-sharing/project/files/upload/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={
                'project_member_id': member.project_member_id,
                'metadata': '{"tags": ["tag 1", "tag 2", "tag 3"]}',
                'data_file': StringIO('just testing...'),
            })

        json = response.json()

        self.assertIn('metadata', json)
        self.assertEqual(response.status_code, 400)

        # data_file missing
        response = self.client.post(
            '/api/direct-sharing/project/files/upload/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={
                'project_member_id': member.project_member_id,
                'metadata': ('{"description": "Test description...", '
                             '"tags": ["tag 1", "tag 2", "tag 3"]}'),
                'tags': '["tag 1", "tag 2", "tag 3"]',
            })

        json = response.json()

        self.assertIn('data_file', json)
        self.assertEqual(response.status_code, 400)

        # project_member_id missing
        response = self.client.post(
            '/api/direct-sharing/project/files/upload/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={
                'metadata': ('{"description": "Test description...", '
                             '"tags": ["tag 1", "tag 2", "tag 3"]}'),
                'data_file': StringIO('just testing...'),
            })

        json = response.json()

        self.assertIn('project_member_id', json)
        self.assertEqual(response.status_code, 400)

    def test_file_delete(self):
        member = self.update_member(joined=True, authorized=True)

        data_file = ProjectDataFile(
            direct_sharing_project=self.member1_project,
            user=self.member1.user,
            completed=True,
            file='')

        data_file.save()

        response = self.client.post(
            '/api/direct-sharing/project/files/delete/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={
                'project_member_id': member.project_member_id,
                'file_id': data_file.id,
            })

        self.assertEqual(response.json(), {'ids': [data_file.id]})
        self.assertEqual(response.status_code, 200)

    def test_file_delete_bad_request(self):
        member = self.update_member(joined=True, authorized=True)

        response = self.client.post(
            '/api/direct-sharing/project/files/delete/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={
                'project_member_id': member.project_member_id,
                'all_files': True,
                'file_id': 123,
            })

        self.assertEqual(response.json(), {
            'too_many':
                'one of file_id, file_basename, or all_files is required',
        })

        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            '/api/direct-sharing/project/files/delete/?access_token={}'.format(
                self.member1_project.master_access_token),
            data={})

        self.assertEqual(response.json(), {
            'project_member_id': ['This field is required.'],
        })

        self.assertEqual(response.status_code, 400)

    def test_direct_upload(self):
        member = self.update_member(joined=True, authorized=True)

        response = self.client.post(
            '/api/direct-sharing/project/files/upload/direct/?access_token={}'
            .format(self.member1_project.master_access_token),
            data={
                'project_member_id': member.project_member_id,
                'filename': 'test-file.json',
                'metadata': ('{"description": "Test description...", '
                             '"tags": ["tag 1", "tag 2", "tag 3"]}'),
            })

        json = response.json()

        self.assertIn('id', json)
        self.assertIn('url', json)
        self.assertIn('/member-files/direct-sharing-', json['url'])

        self.assertEqual(response.status_code, 201)
