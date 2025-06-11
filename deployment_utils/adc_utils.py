import google.auth


def print_adc_info():
    """Checks for and prints information about Application Default Credentials."""
    print(get_adc_info_string())
def _get_adc_details() -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Helper function to get ADC details. Returns (found_status, project_id, type, email, quota_project_id)."""
    try:
        # Attempt to get default credentials and the auto-detected project ID
        credentials, detected_project_id = google.auth.default()
        adc_found = "Yes"
        project_id_str = detected_project_id or "Not detected automatically."

        # Check if the credentials object has the service_account_email attribute
        quota_project_id = getattr(credentials, 'quota_project_id', None) # Get quota project if available
        adc_email = None
        if hasattr(credentials, "service_account_email"):
            adc_email = credentials.service_account_email
            adc_type = "Service Account"
        # Check if it might be user credentials (common case for gcloud login)
        elif hasattr(credentials, "refresh_token") or isinstance(credentials, google.oauth2.credentials.Credentials):
             adc_type = "User Credentials (e.g., gcloud auth application-default login)"
             # Note: User email is not typically available directly on the credential object itself.
        else:
            # Fallback for other credential types if needed
            adc_type = f"Other ({type(credentials).__name__})"
        return adc_found, project_id_str, adc_type, adc_email, quota_project_id
    except google.auth.exceptions.DefaultCredentialsError:
        return "No (Could not automatically find credentials)", None, None, None, None


def get_adc_info_string() -> str:
    """Checks for and returns a formatted string with ADC information."""
    adc_found, project_id_str, adc_type, adc_email, quota_project_id = _get_adc_details()
    lines = [
        "--- Application Default Credentials (ADC) ---",
        f"ADC Found: {adc_found}",
    ]
    if project_id_str:
        lines.append(f"ADC Project ID: {project_id_str}")
    if adc_type:
        lines.append(f"ADC Type: {adc_type}")
    if adc_email:
        lines.append(f"ADC Email: {adc_email}")
    if quota_project_id:
        lines.append(f"ADC Quota Project: {quota_project_id}")
    lines.append("---------------------------------------------")
    return "\n".join(lines)
