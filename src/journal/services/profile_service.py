"""
Profile service for managing trader profiles
"""

from __future__ import annotations

import structlog

from ..dto import ProfileIn, ProfileOut, ProfileUpdate
from ..repositories.profile import ProfileRepository


class ProfileService:
    """Service for managing trader profiles with business logic"""

    def __init__(self, profile_repository: ProfileRepository) -> None:
        self._profile_repo = profile_repository
        self._logger = structlog.get_logger(__name__)

    def create_profile(
        self, name: str, description: str = None, csv_format: str = None
    ) -> ProfileOut:
        """Create a new trader profile"""
        self._logger.info("Creating new profile", name=name)

        profile_data = ProfileIn(
            name=name,
            description=description,
            is_active=True,
            default_csv_format=csv_format or "tradersync",
        )

        try:
            profile = self._profile_repo.create_profile(profile_data)
            self._logger.info(
                "Profile created successfully", profile_id=profile.id, name=profile.name
            )
            return profile
        except ValueError as e:
            self._logger.warning("Profile creation failed", name=name, error=str(e))
            raise

    def get_profile(self, profile_id: int) -> ProfileOut | None:
        """Get a profile by ID"""
        return self._profile_repo.get_profile(profile_id)

    def get_profile_by_name(self, name: str) -> ProfileOut | None:
        """Get a profile by name"""
        return self._profile_repo.get_profile_by_name(name)

    def list_all_profiles(self) -> list[ProfileOut]:
        """List all profiles"""
        return self._profile_repo.list_profiles(active_only=False)

    def list_active_profiles(self) -> list[ProfileOut]:
        """List only active profiles"""
        return self._profile_repo.list_profiles(active_only=True)

    def update_profile(self, profile_id: int, **kwargs) -> ProfileOut | None:
        """Update a profile with the given fields"""
        update_data = ProfileUpdate(**kwargs)

        try:
            profile = self._profile_repo.update_profile(profile_id, update_data)
            if profile:
                self._logger.info("Profile updated successfully", profile_id=profile_id)
            return profile
        except ValueError as e:
            self._logger.warning("Profile update failed", profile_id=profile_id, error=str(e))
            raise

    def activate_profile(self, profile_id: int) -> ProfileOut | None:
        """Activate a profile"""
        self._logger.info("Activating profile", profile_id=profile_id)
        return self.update_profile(profile_id, is_active=True)

    def deactivate_profile(self, profile_id: int) -> ProfileOut | None:
        """Deactivate a profile"""
        self._logger.info("Deactivating profile", profile_id=profile_id)
        return self.update_profile(profile_id, is_active=False)

    def delete_profile(self, profile_id: int, force: bool = False) -> bool:
        """Delete a profile

        Args:
            profile_id: ID of the profile to delete
            force: If True, delete profile even if it has associated trades
        """
        self._logger.info("Attempting to delete profile", profile_id=profile_id, force=force)

        try:
            result = self._profile_repo.delete_profile(profile_id, force=force)
            if result:
                if force:
                    self._logger.warning(
                        "Profile and associated trades deleted", profile_id=profile_id
                    )
                else:
                    self._logger.info("Profile deleted successfully", profile_id=profile_id)
            else:
                self._logger.warning("Profile not found for deletion", profile_id=profile_id)
            return result
        except ValueError as e:
            self._logger.warning("Profile deletion failed", profile_id=profile_id, error=str(e))
            raise

    def get_default_profile(self) -> ProfileOut:
        """Get the default profile, ensuring one exists"""
        profile = self._profile_repo.get_default_profile()
        if profile:
            return profile

        # No default profile found, ensure one exists
        self._logger.info("No default profile found, creating one")
        return self._profile_repo.ensure_default_profile_exists()

    def get_profile_summary(self, profile_id: int) -> dict:
        """Get profile summary with trade count and other stats"""
        profile = self.get_profile(profile_id)
        if not profile:
            return {}

        trade_count = self._profile_repo.get_profile_trade_count(profile_id)

        return {
            "profile": profile,
            "trade_count": trade_count,
            "can_delete": trade_count == 0,
        }

    def validate_profile_name(self, name: str, exclude_id: int = None) -> bool:
        """Validate if a profile name is available"""
        existing = self.get_profile_by_name(name)
        if not existing:
            return True

        # Name exists, check if it's the same profile we're updating
        return exclude_id is not None and existing.id == exclude_id

    def duplicate_profile(self, profile_id: int, new_name: str) -> ProfileOut:
        """Create a copy of an existing profile with a new name"""
        source_profile = self.get_profile(profile_id)
        if not source_profile:
            raise ValueError(f"Profile {profile_id} not found")

        self._logger.info("Duplicating profile", source_id=profile_id, new_name=new_name)

        profile_data = ProfileIn(
            name=new_name,
            description=f"Copy of {source_profile.name}",
            is_active=True,
            default_csv_format=source_profile.default_csv_format,
        )

        return self._profile_repo.create_profile(profile_data)

    def get_profile_choices(self) -> list[tuple[int, str]]:
        """Get profile choices for UI dropdowns as (id, display_name) tuples"""
        active_profiles = self.list_active_profiles()
        return [(p.id, p.name) for p in active_profiles]

    def switch_to_profile(self, profile_id: int) -> ProfileOut:
        """Switch to a different profile, ensuring it exists and is active"""
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if not profile.is_active:
            raise ValueError(f"Profile '{profile.name}' is not active")

        self._logger.info("Switching to profile", profile_id=profile_id, name=profile.name)
        return profile

    def delete_profile_data(self, profile_id: int) -> dict:
        """Delete all data (trades) associated with a profile

        Args:
            profile_id: ID of the profile whose data should be deleted

        Returns:
            Dictionary with deletion results: {'trades_deleted': int, 'profile_name': str}
        """
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        self._logger.warning(
            "Deleting all data for profile", profile_id=profile_id, name=profile.name
        )

        try:
            trades_deleted = self._profile_repo.delete_profile_data(profile_id)

            result = {"trades_deleted": trades_deleted, "profile_name": profile.name}

            if trades_deleted > 0:
                self._logger.warning(
                    "Profile data deletion completed",
                    profile_id=profile_id,
                    profile_name=profile.name,
                    trades_deleted=trades_deleted,
                )
            else:
                self._logger.info(
                    "No data to delete for profile",
                    profile_id=profile_id,
                    profile_name=profile.name,
                )

            return result

        except Exception as e:
            self._logger.error(
                "Profile data deletion failed",
                profile_id=profile_id,
                profile_name=profile.name,
                error=str(e),
            )
            raise
