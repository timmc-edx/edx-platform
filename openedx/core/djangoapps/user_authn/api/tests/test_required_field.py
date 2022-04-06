"""
Tests for RequiredFieldsData View
"""
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from openedx.core.djangolib.testing.utils import skip_unless_lms


@skip_unless_lms
class RequiredFieldsDataViewTest(APITestCase):
    """
    Tests for the end-point that returns required fields.
    """

    def setUp(self):
        super().setUp()

        self.url = reverse('required_fields')

    @override_settings(REGISTRATION_EXTRA_FIELDS={"first_name": "optional", "city": "optional"})
    def test_required_fields_not_configured(self):
        """
        Test that when no required fields are configured in REGISTRATION_EXTRA_FIELDS
        settings, then API returns proper response.
        """
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data.get('error_code') == 'required_fields_configured_incorrectly'

    @override_settings(
        REGISTRATION_EXTRA_FIELDS={'state': 'required', 'last_name': 'required', 'first_name': 'required'},
        REGISTRATION_FIELD_ORDER=['first_name', 'last_name', 'state'],
    )
    def test_field_order(self):
        """
        Test that order of fields
        """
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert list(response.data['fields'].keys()) == ['first_name', 'last_name', 'state']
