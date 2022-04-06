"""
Field Descriptions
"""
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _

from common.djangoapps.student.models import UserProfile
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from openedx.core.djangoapps.user_api import accounts
from openedx.core.djangoapps.user_authn.api.constants import SUPPORTED_FIELDS_TYPES

FIELD_TYPE_MAP = {
    forms.CharField: "text",
    forms.PasswordInput: "password",
    forms.ChoiceField: "select",
    forms.TypedChoiceField: "select",
    forms.Textarea: "textarea",
    forms.BooleanField: "checkbox",
    forms.EmailField: "email",
}


def add_extension_form_field(field_name, custom_form, field_description, field_type='required'):
    """
    Returns Extension form field values
    """
    restrictions = {}
    if field_type == 'required':
        if getattr(field_description, 'max_length', None):
            restrictions['max_length'] = field_description.max_length
        if getattr(field_description, 'min_length', None):
            restrictions['min_length'] = field_description.min_length

    field_options = getattr(
        getattr(custom_form, 'Meta', None), 'serialization_options', {}
    ).get(field_name, {})
    field_type = field_options.get('field_type', FIELD_TYPE_MAP.get(field_description.__class__))

    if not field_type:
        raise ImproperlyConfigured(
            f'Field type {field_type} not recognized for registration extension field {field_name}.'
        )

    return {
        'name': field_name,
        'label': field_description.label,
        'default': field_options.get('default'),
        'placeholder': field_description.initial,
        'instructions': field_description.help_text,
        'options': getattr(field_description, 'choices', None),
        'error_message': field_description.error_messages if field_type == 'required' else '',
        'restrictions': restrictions,
        'type': field_type,

    }


def _add_field_with_configurable_select_options(field_name, field_label, error_message=''):
    """
    Returns a field description
        If select options are given for this field in EXTRA_FIELD_OPTIONS, it
        will be a select type otherwise it will be a text type.
    """
    field_attributes = {
        'name': field_name,
        'label': field_label,
        'error_message': error_message,
    }
    extra_field_options = configuration_helpers.get_value('EXTRA_FIELD_OPTIONS')
    if extra_field_options is None or extra_field_options.get(field_name) is None:
        field_attributes.update({
            'type': SUPPORTED_FIELDS_TYPES['TEXT'],
        })
    else:
        field_options = extra_field_options.get(field_name)
        options = [(str(option.lower()), option) for option in field_options]
        field_attributes.update({
            'type': SUPPORTED_FIELDS_TYPES['SELECT'],
            'options': options
        })

    return field_attributes


def add_level_of_education_field():
    """
    Returns the level of education field description
    """
    # Translators: This label appears above a dropdown menu used to select
    # the user's highest completed level of education.
    education_level_label = _("Highest level of education completed")

    # pylint: disable=translation-of-non-string
    options = [(name, _(label)) for name, label in UserProfile.LEVEL_OF_EDUCATION_CHOICES]

    if settings.ENABLE_COPPA_COMPLIANCE:
        options = list(filter(lambda op: op[0] != 'el', options))

    return {
        'name': 'level_of_education',
        'type': SUPPORTED_FIELDS_TYPES['SELECT'],
        'label': education_level_label,
        'error_message': accounts.REQUIRED_FIELD_LEVEL_OF_EDUCATION_MSG,
        'options': options,
    }


def add_gender_field():
    """
    Returns the gender field description
    """
    # Translators: This label appears above a dropdown menu used to select
    # the user's gender.
    gender_label = _("Gender")

    # pylint: disable=translation-of-non-string
    options = [(name, _(label)) for name, label in UserProfile.GENDER_CHOICES]
    return {
        'name': 'gender',
        'type': SUPPORTED_FIELDS_TYPES['SELECT'],
        'label': gender_label,
        'error_message': accounts.REQUIRED_FIELD_GENDER_MSG,
        'options': options,
    }


def add_year_of_birth_field():
    """
    Returns the year of birth field description
    """
    # Translators: This label appears above a dropdown menu on the form
    # used to select the user's year of birth.
    year_of_birth_label = _("Year of birth")

    options = [(str(year), str(year)) for year in UserProfile.VALID_YEARS]
    return {
        'name': 'year_of_birth',
        'type': SUPPORTED_FIELDS_TYPES['SELECT'],
        'label': year_of_birth_label,
        'error_message': accounts.REQUIRED_FIELD_YEAR_OF_BIRTH_MSG,
        'options': options,
    }


def add_goals_field():
    """
    Returns the goals field description
    """
    # Translators: This phrase appears above a field meant to hold
    # the user's reasons for registering with edX.
    goals_label = _("Tell us why you're interested in {platform_name}").format(
        platform_name=configuration_helpers.get_value("PLATFORM_NAME", settings.PLATFORM_NAME)
    )

    return {
        'name': 'goals',
        'type': SUPPORTED_FIELDS_TYPES['TEXTAREA'],
        'label': goals_label,
        'error_message': accounts.REQUIRED_FIELD_GOALS_MSG,
    }


def add_profession_field():
    """
    Returns the profession field description
    """
    # Translators: This label appears above a dropdown menu to select
    # the user's profession
    profession_label = _("Profession")
    return _add_field_with_configurable_select_options('profession', profession_label)


def add_specialty_field():
    """
    Returns the user speciality field description
    """
    # Translators: This label appears above a dropdown menu to select
    # the user's specialty
    specialty_label = _("Specialty")
    return _add_field_with_configurable_select_options('specialty', specialty_label)


def add_company_field():
    """
    Returns the company field descriptions
    """
    # Translators: This label appears above a field which allows the
    # user to input the Company
    company_label = _("Company")
    return _add_field_with_configurable_select_options('company', company_label)


def add_title_field():
    """
    Returns the title field description
    """
    # Translators: This label appears above a field which allows the
    # user to input the Title
    title_label = _("Title")
    return _add_field_with_configurable_select_options('title', title_label)


def add_job_title_field():
    """
    Returns the title field description
    """
    # Translators: This label appears above a field which allows the
    # user to input the Job Title
    job_title_label = _("Job Title")
    return _add_field_with_configurable_select_options('job_title', job_title_label)


def add_first_name_field():
    """
    Returns the first name field description
    """
    # Translators: This label appears above a field which allows the
    # user to input the First Name
    first_name_label = _("First Name")

    return {
        'name': 'first_name',
        'type': SUPPORTED_FIELDS_TYPES['TEXT'],
        'label': first_name_label,
        'error_message': accounts.REQUIRED_FIELD_FIRST_NAME_MSG,
    }


def add_last_name_field():
    """
    Returns the last name field description
    """
    # Translators: This label appears above a field which allows the
    # user to input the Last Name
    last_name_label = _("Last Name")

    return {
        'name': 'last_name',
        'type': SUPPORTED_FIELDS_TYPES['TEXT'],
        'label': last_name_label,
        'error_message': accounts.REQUIRED_FIELD_LAST_NAME_MSG,
    }


def add_mailing_address_field():
    """
    Returns the mailing address field description
    """
    # Translators: This label appears above a field
    # meant to hold the user's mailing address.
    mailing_address_label = _("Mailing address")

    return {
        'name': 'mailing_address',
        'type': SUPPORTED_FIELDS_TYPES['TEXTAREA'],
        'label': mailing_address_label,
        'error_message': accounts.REQUIRED_FIELD_MAILING_ADDRESS_MSG,
    }


def add_state_field():
    """
    Returns a State/Province/Region field to a description
    """
    # Translators: This label appears above a field
    # which allows the user to input the State/Province/Region in which they live.
    state_label = _("State/Province/Region")

    return {
        'name': 'state',
        'type': SUPPORTED_FIELDS_TYPES['TEXT'],
        'label': state_label,
        'error_message': accounts.REQUIRED_FIELD_STATE_MSG,
    }


def add_city_field():
    """
    Returns a city field to a description
    """
    # Translators: This label appears above a field
    # which allows the user to input the city in which they live.
    city_label = _("City")

    return {
        'name': 'city',
        'type': SUPPORTED_FIELDS_TYPES['TEXT'],
        'label': city_label,
        'error_message': accounts.REQUIRED_FIELD_CITY_MSG,
    }


def add_honor_code_field(separate_honor_and_tos=False):
    """
    Returns a honor code field to a description and this field will be display
    directly on AuthnMFE
    """
    # Translators: "Terms of Service" is a legal document users must agree to
    # in order to register a new account.
    terms_label = "Honor Code" if separate_honor_and_tos else "Terms of Service and Honor Code"
    platform_name = configuration_helpers.get_value("PLATFORM_NAME", settings.PLATFORM_NAME)
    error_msg = f'You must agree to the {platform_name} {terms_label}'
    return {
        'name': terms_label,
        'type': SUPPORTED_FIELDS_TYPES['CHECKBOX' if separate_honor_and_tos else 'TEXT'],
        'error_message': error_msg,
    }


def add_country_field():
    """
    Returns a country name to a description and this field will be display
    directly on AuthnMFE
    """
    # Translators: This label appears above a dropdown menu on the registration
    # form used to select the country in which the user lives.

    country_label = _("Country or Region of Residence")

    return {
        'name': 'country',
        'type': SUPPORTED_FIELDS_TYPES['SELECT'],
        'label': country_label,
        'error_message': accounts.REQUIRED_FIELD_COUNTRY_MSG,
    }
