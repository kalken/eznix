/* eznix-auth: checks a system password for the eznix service on NixOS.
 *
 * Run through the setuid wrapper security.wrappers.eznix-auth (nixos.nix), which only the
 * group eznix may execute. Reads a user name and a password from stdin, one per line, and
 * exits 0 when PAM accepts them, 1 when not, 2 when it could not become root. It answers
 * only for the users in ALLOWED, which nixos.nix compiles in (-include of a header made from
 * services.eznix.users), never for anyone the caller names.
 *
 * It was a Python script until 2026-10-15, when nixpkgs began refusing a wrapper whose
 * program is not an ELF binary (nixos/wrappers: "enforce target executable is ELF", in
 * nixos-unstable since 2026-10-03): a script's interpreter reads its environment, which the
 * caller of a setuid program controls. Same behaviour, with the account check added
 * (pam_acct_mgmt), so a locked or expired account is refused as at a console login. */
#include <security/pam_appl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static const char *password;

/* Answers every prompt PAM puts with the password, and anything else with nothing. */
static int converse(int n, const struct pam_message **msg, struct pam_response **resp, void *data) {
    (void)data;
    struct pam_response *r = calloc(n, sizeof *r);
    if (!r) return PAM_BUF_ERR;
    for (int i = 0; i < n; i++) {
        if (msg[i]->msg_style == PAM_PROMPT_ECHO_OFF || msg[i]->msg_style == PAM_PROMPT_ECHO_ON) {
            r[i].resp = strdup(password);
            if (!r[i].resp) {
                for (int j = 0; j < i; j++) free(r[j].resp);
                free(r);
                return PAM_BUF_ERR;
            }
        }
    }
    *resp = r;
    return PAM_SUCCESS;
}

int main(void) {
    static char buf[4097];
    size_t len = 0;
    ssize_t k;
    int ok = 0, rc;

    /* Nothing of the caller's environment reaches PAM's modules. */
    clearenv();
    /* Root in full, not only the effective id the wrapper gives: pam_unix then reads
       /etc/shadow itself instead of asking unix_chkpwd, which checks only the caller's own. */
    if (setgid(0) != 0 || setuid(0) != 0) return 2;

    while (len < sizeof buf - 1 && (k = read(0, buf + len, sizeof buf - 1 - len)) > 0) len += k;
    buf[len] = '\0';
    char *nl = strchr(buf, '\n');
    if (!nl) return 1;
    *nl = '\0';
    const char *user = buf;
    char *pw = nl + 1;
    pw[strcspn(pw, "\n")] = '\0';

    for (const char **a = ALLOWED; *a; a++)
        if (strcmp(*a, user) == 0) ok = 1;
    if (!ok) return 1;

    password = pw;
    struct pam_conv conv = { converse, NULL };
    pam_handle_t *h = NULL;
    if (pam_start("login", user, &conv, &h) != PAM_SUCCESS) return 1;
    rc = pam_authenticate(h, PAM_SILENT);
    if (rc == PAM_SUCCESS) rc = pam_acct_mgmt(h, PAM_SILENT);
    pam_end(h, rc);
    memset(buf, 0, sizeof buf);
    return rc == PAM_SUCCESS ? 0 : 1;
}
