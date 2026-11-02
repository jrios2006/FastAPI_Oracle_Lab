"""
module.config_loader
====================

Cargador robusto de archivos JSON con detección automática de encoding.
Implementado como clase para mantener consistencia con el ecosistema del proyecto.

Version: 1.1.0
Build date: 2026-04-10

Librerías necesarias:
---------------------
- charset-normalizer: Para detectar encodings no estándar.
"""

import json
from pathlib import Path
from typing import Any, Dict
from charset_normalizer import from_path
from utils.logger import get_logger

class ConfigLoader:
    """
    Clase encargada de la gestión y lectura de archivos de configuración JSON.
    
    Attributes
    ----------
    logger : logging.Logger
        Instancia del logger para trazabilidad.
    """

    def __init__(self):
        self.logger = get_logger("ConfigLoader")

    def load(self, path: str | Path) -> Dict[str, Any]:
        """
        Carga un fichero JSON y devuelve su contenido como diccionario.
        
        Soporta UTF-8, UTF-8-sig y detección automática vía charset-normalizer.

        Args:
            path (str | Path): Ruta al fichero JSON.

        Returns:
            dict: Contenido del JSON o diccionario vacío en caso de error.
        """
        file_path = Path(path)

        if not file_path.exists():
            self.logger.warning(f"No se encuentra el fichero: {path}")
            return {}

        # 1. Intentos directos con codificaciones estándar
        content = self._try_standard_encodings(file_path)
        if content is not None:
            return content

        # 2. Fallback: Detección automática de codificación
        return self._detect_and_load(file_path)

    def _try_standard_encodings(self, file_path: Path) -> Dict[str, Any] | None:
        """Prueba las codificaciones más comunes (UTF-8 y UTF-8 con BOM)."""
        for enc in ("utf-8", "utf-8-sig"):
            try:
                with open(file_path, "r", encoding=enc) as f:
                    return json.load(f)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            except Exception as e:
                self.logger.error(f"Error inesperado leyendo {file_path.name} con {enc}: {e}")
        return None

    def _detect_and_load(self, file_path: Path) -> Dict[str, Any]:
        """Usa charset-normalizer para resolver archivos con codificación incierta."""
        try:
            result = from_path(file_path).best()
            if result:
                self.logger.info(f"Encoding detectado automáticamente para {file_path.name}")
                return json.loads(str(result))
        except Exception as e:
            self.logger.error(f"Fallo en detección automática de encoding para {file_path}: {e}")

        self.logger.error(f"Incapaz de parsear el fichero JSON: {file_path}")
        return {}