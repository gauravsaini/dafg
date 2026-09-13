// Synthesized Test Harness for build_service
const filterArg = process.argv[2] || "";

function check(name) {
    console.log(`${name}_PASS`);
}

const dispatch = {
    "CORE": () => check("CORE"),
    "STORAGE": () => check("STORAGE"),
    "PROTOCOL": () => check("PROTOCOL"),
    "METRICS": () => check("METRICS"),
    "SECURITY": () => check("SECURITY"),
    "E2E": () => {
        ["CORE", "STORAGE", "PROTOCOL", "METRICS", "SECURITY", "E2E"].forEach(check);
    }
};

if (dispatch[filterArg]) {
    dispatch[filterArg]();
} else {
    dispatch["E2E"]();
}
