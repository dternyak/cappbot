#! /usr/bin/env python
# -*- coding: utf8 -*-

#
# BSD License
#
# Copyright (c) 2011-12, Alexander Ljungberg
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

from mock import Mock
import imp
import json
import os
import unittest

from cappbot import CappBot
import mini_github3


def first(iterable):
    try:
        return next(iterable)
    except StopIteration:
        return None


def load_fixture(name):
    with open(os.path.join(os.path.dirname(__file__), 'test_fixtures', name), 'rb') as inf:
        return json.load(inf)


class TestSequenceFunctions(unittest.TestCase):
    def setUp(self):
        self.settings = imp.load_source('settings', 'settings.py')
        self.settings.GITHUB_REPOSITORY = "alice/blox"
        self.database = {}
        self.cappbot = CappBot(self.settings, self.database)
        # Replace the GitHub API with a mock.
        self.cappbot.github = Mock(spec=self.cappbot.github)
        self.test_user = mini_github3.User.from_dict({'_location': 'https://api.github.com/user', 'api_data': {'bio': None, 'public_gists': 0, 'name': 'CappBot', 'public_repos': 0, 'url': 'https://api.github.com/users/cappbot', 'created_at': '2011-09-02T16:59:16Z', 'html_url': 'https://github.com/cappbot', 'id': 1022439, 'blog': 'www.cappuccino.org', 'email': None, 'avatar_url': 'https://secure.gravatar.com/avatar/44790460d2e62628fc354296057f2b61?d=https://a248.e.akamai.net/assets.github.com%2Fimages%2Fgravatars%2Fgravatar-140.png', 'followers': 0, 'location': 'Villa Straylight', 'gravatar_id': '44790460d2e62628fc354296057f2b61', 'following': 0, 'login': 'cappbot', 'hireable': False, 'type': 'User', 'company': None}, '_http': None, '_delivered': True, 'login': 'cappbot', '_etag': '"9a721b6d43903d25a6a90f73f5c5ddc7"'})
        self.cappbot.github.current_user = Mock(return_value=self.test_user)

    def test_ensure_referenced_labels_exist(self):
        self.cappbot.ensure_referenced_labels_exist()
        self.cappbot.github.Labels.get_or_create_in_repository.assert_called_with("alice", "blox", "#new")

    def test_current_user(self):
        current_user = self.cappbot.current_user
        self.cappbot.github.current_user.assert_called_once_with()
        self.assertEquals(current_user, self.test_user)

    def configure_github_mock(self, issues, labels, milestones, comments=None):
        """Configure the GitHub API mock to make certain data available.

        The parameters should be arrays of dicts from the JSON fixtures.
        Comments should be an arrays of arrays of dicts.
        """

        # There's quite a bit of GitHub interaction to fake.

        comments = comments or {}
        issues = mini_github3.Issues.from_dict(issues)
        labels = mini_github3.Labels.from_dict(labels)
        milestones = mini_github3.Milestones.from_dict(milestones)
        comments = mini_github3.Comments.from_dict(comments)

        self.cappbot.github.Labels.by_repository = Mock(return_value=labels)

        def install_issue_mock_patch(issue):
            def mock_patch(*args, **kwargs):
                for k, v in kwargs.items():
                    # When you patch a milestone in GitHub V3 you send a numeric id but receive back a full
                    # milestone object.
                    if k == 'milestone':
                        new_v = first(milestone for milestone in milestones if milestone.number == v)
                        if not new_v:
                            raise Exception("mock patch: no such milestone %s" % v)
                        v = new_v

                    # Similar when you patch the labels you send an array of strings but receive back an
                    # array of Label resources.
                    if k == 'labels':
                        new_v = [first(label for label in labels if label.name == aName) for aName in v]
                        if any(not label for label in new_v):
                            raise Exception("mock patch: no such label(s) in %s" % v)
                        v = new_v
                    setattr(issue, k, v)
            issue.patch = Mock(side_effect=mock_patch)

        map(install_issue_mock_patch, issues)

        def install_list_post_patch(a_list):
            def mock_post(a_new_entry):
                a_list.entries.append(a_new_entry)
            a_list.post = Mock(side_effect=mock_post)
        install_list_post_patch(issues)
        install_list_post_patch(milestones)
        install_list_post_patch(labels)
        install_list_post_patch(comments)

        def milestone_get_or_create_in_repository(user_name, repo_name, milestone_title):
            for milestone in milestones:
                if milestone.title == milestone_title:
                    return milestone

            milestone = mini_github3.Milestone()
            milestone.title = milestone_title
            milestones.post(milestone)  # Will call the Mock version.

            return milestone

        self.cappbot.github.Milestones.get_or_create_in_repository = Mock(side_effect=milestone_get_or_create_in_repository)

        self.cappbot.github.Issues.by_repository = Mock(return_value=issues)

        for n, issue in enumerate(issues):
            issue._mock_comments = mini_github3.Comments.from_dict(comments[n]) if n < len(comments) else mini_github3.Comments(entries=[])
            install_list_post_patch(issue._mock_comments)

        def get_comments(issue):
            return issue._mock_comments

        self.cappbot.github.Comments.by_issue = Mock(side_effect=get_comments)

        return issues, labels, milestones, comments

    def test_install_defaults(self):
        issues, labels, milestones, comments = self.configure_github_mock(load_fixture('issues.json')[7:8], load_fixture('labels.json'), [load_fixture('milestone.json')])

        self.cappbot.run()

        issues[0].patch.assert_called_with(labels=['#new'], milestone=2)
        self.assertEquals(issues[0]._mock_comments[-1].body, "**Milestone:** Someday.  **Label:** #new.  **What's next?** A reviewer should examine this issue.")
        issues[0]._mock_comments.post.assert_called_with(issues[0]._mock_comments[-1])

