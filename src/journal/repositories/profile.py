"""
Profile repository for managing trader profiles
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Engine, select, update, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from ..db.models import Profile
from ..dto import ProfileIn, ProfileOut, ProfileUpdate
from ..services.cache import TTLCache
from .base import BaseRepository


class ProfileRepository(BaseRepository):
    """Repository for managing trader profiles"""

    def __init__(self, engine: Engine, cache: TTLCache) -> None:
        super().__init__(engine, Profile)
        self._cache = cache
        self._Session = sessionmaker(bind=engine)

    def create_profile(self, profile_data: ProfileIn) -> ProfileOut:
        """Create a new profile"""
        with self._Session() as session:
            try:
                profile = Profile(
                    name=profile_data.name,
                    description=profile_data.description,
                    is_active=profile_data.is_active,
                    default_csv_format=profile_data.default_csv_format,
                )
                session.add(profile)
                session.commit()
                session.refresh(profile)
                
                # Clear cache
                self._cache.invalidate_prefix("profiles:")
                
                return ProfileOut.model_validate(profile)
            except IntegrityError as e:
                session.rollback()
                if "unique" in str(e).lower():
                    raise ValueError(f"Profile name '{profile_data.name}' already exists")
                raise

    def get_profile(self, profile_id: int) -> ProfileOut | None:
        """Get a profile by ID"""
        cache_key = f"profiles:by_id:{profile_id}"
        cached = self._cache.get(cache_key)
        if cached:
            return ProfileOut.model_validate(cached)

        with self._Session() as session:
            stmt = select(Profile).where(Profile.id == profile_id)
            profile = session.scalar(stmt)
            
            if profile:
                profile_out = ProfileOut.model_validate(profile)
                self._cache.set(cache_key, profile_out.model_dump(), ttl=300)
                return profile_out
            return None

    def get_profile_by_name(self, name: str) -> ProfileOut | None:
        """Get a profile by name"""
        cache_key = f"profiles:by_name:{name}"
        cached = self._cache.get(cache_key)
        if cached:
            return ProfileOut.model_validate(cached)

        with self._Session() as session:
            stmt = select(Profile).where(Profile.name == name)
            profile = session.scalar(stmt)
            
            if profile:
                profile_out = ProfileOut.model_validate(profile)
                self._cache.set(cache_key, profile_out.model_dump(), ttl=300)
                return profile_out
            return None

    def list_profiles(self, active_only: bool = False) -> List[ProfileOut]:
        """List all profiles, optionally filtering by active status"""
        cache_key = f"profiles:list:active_{active_only}"
        cached = self._cache.get(cache_key)
        if cached:
            return [ProfileOut.model_validate(p) for p in cached]

        with self._Session() as session:
            stmt = select(Profile).order_by(Profile.name)
            if active_only:
                stmt = stmt.where(Profile.is_active == True)
            
            profiles = session.scalars(stmt).all()
            profile_list = [ProfileOut.model_validate(p) for p in profiles]
            
            self._cache.set(cache_key, [p.model_dump() for p in profile_list], ttl=300)
            return profile_list

    def update_profile(self, profile_id: int, update_data: ProfileUpdate) -> ProfileOut | None:
        """Update a profile"""
        with self._Session() as session:
            try:
                # Build update dict, excluding None values
                update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
                
                if not update_dict:
                    # Nothing to update
                    return self.get_profile(profile_id)
                
                # Add updated_at timestamp
                from datetime import datetime
                update_dict['updated_at'] = datetime.now()
                
                stmt = (
                    update(Profile)
                    .where(Profile.id == profile_id)
                    .values(**update_dict)
                    .returning(Profile)
                )
                
                result = session.execute(stmt)
                profile = result.scalar_one_or_none()
                
                if profile:
                    session.commit()
                    # Clear cache
                    self._cache.invalidate_prefix("profiles:")
                    return ProfileOut.model_validate(profile)
                
                return None
                
            except IntegrityError as e:
                session.rollback()
                if "unique" in str(e).lower():
                    raise ValueError(f"Profile name '{update_data.name}' already exists")
                raise

    def delete_profile(self, profile_id: int, force: bool = False) -> bool:
        """Delete a profile
        
        Args:
            profile_id: ID of the profile to delete
            force: If True, delete profile even if it has associated trades
        """
        with self._Session() as session:
            # Check if profile has any trades
            from ..db.models import Trade
            trade_count = session.scalar(
                select(func.count(Trade.id)).where(Trade.profile_id == profile_id)
            )
            
            if trade_count > 0 and not force:
                raise ValueError(f"Cannot delete profile: it has {trade_count} associated trades")
            
            # If force delete and profile has trades, delete trades first
            if force and trade_count > 0:
                delete_trades_stmt = delete(Trade).where(Trade.profile_id == profile_id)
                session.execute(delete_trades_stmt)
            
            stmt = delete(Profile).where(Profile.id == profile_id)
            result = session.execute(stmt)
            
            if result.rowcount > 0:
                session.commit()
                # Clear cache
                self._cache.invalidate_prefix("profiles:")
                return True
            
            return False

    def get_default_profile(self) -> ProfileOut | None:
        """Get the default profile (ID=1) or the first active profile"""
        # Try to get profile with ID=1 first
        profile = self.get_profile(1)
        if profile and profile.is_active:
            return profile
        
        # Otherwise, get the first active profile
        active_profiles = self.list_profiles(active_only=True)
        return active_profiles[0] if active_profiles else None

    def ensure_default_profile_exists(self) -> ProfileOut:
        """Ensure that a default profile exists, creating one if necessary"""
        # Check if profile with ID=1 exists
        profile = self.get_profile(1)
        if profile:
            return profile
        
        # Check if any profiles exist
        all_profiles = self.list_profiles()
        if all_profiles:
            return all_profiles[0]
        
        # Create default profile
        default_profile = ProfileIn(
            name="Default Trader",
            description="Default trading profile",
            is_active=True,
            default_csv_format="tradersync"
        )
        
        return self.create_profile(default_profile)

    def get_profile_trade_count(self, profile_id: int) -> int:
        """Get the number of trades associated with a profile"""
        cache_key = f"profiles:trade_count:{profile_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        with self._Session() as session:
            from ..db.models import Trade
            count = session.scalar(
                select(func.count(Trade.id)).where(Trade.profile_id == profile_id)
            )
            
            self._cache.set(cache_key, count, ttl=60)  # Cache for 1 minute
            return count or 0

    def delete_profile_data(self, profile_id: int) -> int:
        """Delete all data (trades) associated with a profile
        
        Args:
            profile_id: ID of the profile whose data should be deleted
            
        Returns:
            Number of trades deleted
        """
        with self._Session() as session:
            from ..db.models import Trade
            
            # Count trades before deletion for reporting
            trade_count = session.scalar(
                select(func.count(Trade.id)).where(Trade.profile_id == profile_id)
            ) or 0
            
            if trade_count > 0:
                # Delete all trades for this profile
                delete_stmt = delete(Trade).where(Trade.profile_id == profile_id)
                session.execute(delete_stmt)
                session.commit()
                
                # Clear cache
                self._cache.invalidate_prefix("profiles:")
                self._cache.invalidate_prefix("trades:")  # Clear trade-related cache too
            
            return trade_count