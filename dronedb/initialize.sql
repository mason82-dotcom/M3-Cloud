CREATE DATABASE IF NOT EXISTS `RegistryAuth` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS `RegistryHangfire` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

GRANT ALL PRIVILEGES ON `RegistryAuth`.* TO 'registry'@'%';
GRANT ALL PRIVILEGES ON `RegistryHangfire`.* TO 'registry'@'%';
FLUSH PRIVILEGES;
