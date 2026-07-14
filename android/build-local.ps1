$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$JavaHome = 'C:\Program Files\Microsoft\jdk-17.0.12.7-hotspot'
$SdkRoot = Join-Path $RepoRoot '.local\android-sdk'
$Gradle = Join-Path $RepoRoot '.local\gradle\gradle-8.9\bin\gradle.bat'

if (!(Test-Path $JavaHome)) { throw "JDK 17 not found: $JavaHome" }
if (!(Test-Path $SdkRoot)) { throw "Android SDK not found: $SdkRoot" }
if (!(Test-Path $Gradle)) { throw "Gradle not found: $Gradle" }

$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $SdkRoot
$env:ANDROID_SDK_ROOT = $SdkRoot
$env:GRADLE_USER_HOME = Join-Path $RepoRoot '.local\gradle-home'
$env:Path = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\cmdline-tools\latest\bin;$env:Path"

& $Gradle -p (Join-Path $RepoRoot 'android') :app:assembleDebug --no-daemon @args
