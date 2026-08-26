allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

// opus_flutter_android (a transitive plugin dependency) ships with
// compileSdkVersion 33 hardcoded in its own build.gradle, which the AGP
// version bundled with current Flutter rejects because its resolved
// androidx transitives (lifecycle 2.7.0, core 1.13.1, etc.) require
// compileSdk 34+. We don't control that plugin's build file, so force every
// Android library subproject to compile against the same SDK as the app.
subprojects {
    val forceCompileSdk: () -> Unit = {
        extensions.findByType<com.android.build.gradle.BaseExtension>()?.compileSdkVersion(36)
    }
    if (state.executed) {
        forceCompileSdk()
    } else {
        afterEvaluate { forceCompileSdk() }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
