# -*- coding: utf-8 -*-
from gzip import GzipFile
import json
from django.core.paginator import PageNotAnInteger, Paginator
from django.core.paginator import EmptyPage
from django.http.response import Http404, StreamingHttpResponse, HttpResponse
from django.template.base import Template
from django.template.context import Context
from django.views.generic.base import TemplateView, View
from django.views.generic.detail import DetailView
from gitbrowser.conf import config
from gitbrowser.templatetags.gb_tags import time_tag


class ListRepositoriesView(TemplateView):
	template_name = 'repo_list.html'

	def get_context_data(self, **kwargs):
		d = super(ListRepositoriesView, self).get_context_data()
		d['repositories'] = lambda: config.lister.get_repositories(self.request.user)
		return d


class TreeOperationMixin(object):

	def __init__(self, *args, **kwargs):
		self._repo = None

	@property
	def repository(self):
		if not self._repo:
			repo = config.lister.get_repository(self.request.user, self.kwargs['path'])
			if not repo:
				raise Http404

			repo_ref = self.kwargs.get('ref', 'master')
			repo_path = self.kwargs.get('repo_path', '')

			repo.set_list_filter(repo_ref, repo_path)

			self._repo = repo
		return self._repo


class BrowseTreeView(TreeOperationMixin, DetailView):
	template_name = 'repo_browse.html'
	context_object_name = 'repository'

	def get_object(self, queryset=None):
		return self.repository


class RepositoryTreeData(TreeOperationMixin, View):

	def get(self, request, *args, **kwargs):
		def _inner():
			for item, _ in self.repository.items():
				commit = self.repository.get_latest_commit(item)
				yield "data: %s\n\n" % json.dumps({
					'summary_link': Template('''<a class="text-muted"
								href="{% url 'commit' repository.relative_path commit.hexsha %}"
								title="{{commit.summary}}">{{commit.summary}}</a>''').render(Context({
						'repository': self.repository,
						'commit': commit
					})),
					'commit_datetime': time_tag(commit.authored_datetime()),
					'obj': item.hexsha
				})
		return StreamingHttpResponse(_inner(), content_type='text/event-stream')


class BrowseBlobView(TreeOperationMixin, DetailView):
	template_name = 'repo_blob.html'
	context_object_name = 'blob'

	def __init__(self, *args, **kwargs):
		super(BrowseBlobView, self).__init__(*args, **kwargs)
		self._repo = None

	def get_object(self, queryset=None):
		return self.repository.items().next()[0]

	def get_context_data(self, **kwargs):
		return super(BrowseBlobView, self).get_context_data(repository=self.repository)


class CommitDetailView(TreeOperationMixin, DetailView):
	template_name = 'commit_detail.html'
	context_object_name = 'commit'

	def get_object(self, queryset=None):
		return self.repository.get_commit(self.kwargs['commit_id'])

	def get_context_data(self, **kwargs):
		return super(CommitDetailView, self).get_context_data(repository=self.repository)


class RepositoryCommitsListView(TreeOperationMixin, TemplateView):
	template_name = 'repo_commits.html'

	def get_context_data(self, **kwargs):
		d = super(RepositoryCommitsListView, self).get_context_data(repository=self.repository)

		paginator = Paginator(self.repository.commit_list, 25) # Show 25 contacts per page

		page = self.request.GET.get('page')
		try:
			commits = paginator.page(page)
		except PageNotAnInteger:
			commits = paginator.page(1)
		except EmptyPage:
			commits = paginator.page(paginator.num_pages)

		d['paginator'] = paginator
		d['commits'] = commits
		return d


class RepositoryTagsView(TreeOperationMixin, TemplateView):
	template_name = 'repo_tags.html'

	def get_context_data(self, **kwargs):
		return super(RepositoryTagsView, self).get_context_data(repository=self.repository)


class RepositoryArchiveView(TreeOperationMixin, View):

	def get(self, *args, **kwargs):
		tag = kwargs.get('tag')
		format = kwargs.get('format')

		filename = '%s-%s.tar.%s' % (self.repository.clean_name, tag, format)

		resp = HttpResponse(content_type='application/x-gtar')
		resp['Content-Disposition'] = 'attachment; filename=%s' % filename

		with GzipFile(filename=filename, fileobj=resp, mode='wb', compresslevel=5) as gz:
			self.repository.archive(gz, treeish=tag)

		return resp