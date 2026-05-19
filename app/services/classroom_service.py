# app/services/classrooom_service.py
"""
Classroom service
"""
import secrets
import string
from typing import List, Dict, Any, Optional
from app.core.extensions import db
from app.models.classroom import Classroom


class ClassroomService:
    """Classroom management service"""
    
    @staticmethod
    def generate_classroom_code() -> str:
        """
        Generate a unique classroom code
        
        Returns:
            str: A 6-character code consisting of uppercase letters and digits
            
        Raises:
            RuntimeError: If a unique code cannot be generated after 10 attempts
        """
        alphabet = string.ascii_uppercase + string.digits
        
        for _ in range(10):
            code = ''.join(secrets.choice(alphabet) for _ in range(6))
            if not Classroom.query.filter_by(code=code).first():
                return code
        
        raise RuntimeError("failed to generate classroom code")
    
    @staticmethod
    def to_dict(classroom: Classroom) -> Dict[str, Any]:
        """
        Convert a Classroom object to a dictionary
        
        Args:
            classroom: Classroom model instance
            
        Returns:
            dict: Classroom information as a dictionary
        """
        return {
            "id": classroom.id,
            "name": classroom.name,
            "code": getattr(classroom, "code", None),
            "description": classroom.description or "",
            "teacher_id": getattr(classroom, "teacher_id", None),
            "created_at": classroom.created_at.isoformat() if getattr(classroom, "created_at", None) else None,
        }
    
    @staticmethod
    def get_teacher_classrooms(teacher_id: int) -> List[Classroom]:
        """
        Get all classrooms belonging to a teacher
        
        Args:
            teacher_id: Teacher ID
            
        Returns:
            list: A list of Classroom objects
        """
        return Classroom.query.filter_by(teacher_id=teacher_id).order_by(Classroom.id.desc()).all()
    
    @staticmethod
    def create_classroom(teacher_id: int, name: str, description: str = "") -> Classroom:
        """
        Create a new classroom
        
        Args:
            teacher_id: Teacher ID
            name: Classroom name
            description: Classroom description
            
        Returns:
            Classroom: The created Classroom object
            
        Raises:
            ValueError: If the name is empty
        """
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        
        classroom = Classroom(
            name=name,
            description=description.strip(),
            teacher_id=teacher_id,
        )
        
        # If the model has a code field, generate a code
        if hasattr(Classroom, "code"):
            classroom.code = ClassroomService.generate_classroom_code()
        
        db.session.add(classroom)
        db.session.commit()
        
        return classroom
    
    @staticmethod
    def get_classroom_by_id(classroom_id: int) -> Optional[Classroom]:
        """
        Get a classroom by ID
        
        Args:
            classroom_id: Classroom ID
            
        Returns:
            Classroom or None: The Classroom object or None
        """
        return Classroom.query.get(classroom_id)
    
    @staticmethod
    def delete_classroom(classroom_id: int) -> bool:
        """
        Delete a classroom
        
        Args:
            classroom_id: Classroom ID
            
        Returns:
            bool: True if deletion succeeded
        """
        classroom = Classroom.query.get(classroom_id)
        if not classroom:
            return False
        
        db.session.delete(classroom)
        db.session.commit()
        return True
    
    @staticmethod
    def update_classroom(classroom_id: int, name: str = None, description: str = None) -> Optional[Classroom]:
        """
        Update classroom information
        
        Args:
            classroom_id: Classroom ID
            name: New name (optional)
            description: New description (optional)
            
        Returns:
            Classroom or None: The updated Classroom object or None
        """
        classroom = Classroom.query.get(classroom_id)
        if not classroom:
            return None
        
        if name is not None:
            classroom.name = name.strip()
        if description is not None:
            classroom.description = description.strip()
        
        db.session.commit()
        return classroom
    
    @staticmethod
    def is_teacher_owner(teacher_id: int, classroom_id: int) -> bool:
        """
        Check whether the teacher owns the specified classroom
        
        Args:
            teacher_id: Teacher ID
            classroom_id: Classroom ID
            
        Returns:
            bool: True if the teacher owns the classroom
        """
        classroom = Classroom.query.filter_by(id=classroom_id, teacher_id=teacher_id).first()
        return classroom is not None
