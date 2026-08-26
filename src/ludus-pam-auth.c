#include <security/pam_appl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *password;
static int conversation(int count, const struct pam_message **messages, struct pam_response **responses, void *data) {
    (void)data;
    *responses = calloc((size_t)count, sizeof(**responses));
    if (!*responses) return PAM_CONV_ERR;
    for (int i = 0; i < count; i++) {
        if (messages[i]->msg_style != PAM_PROMPT_ECHO_OFF) return PAM_CONV_ERR;
        (*responses)[i].resp = strdup(password);
        if (!(*responses)[i].resp) return PAM_CONV_ERR;
    }
    return PAM_SUCCESS;
}
int main(int argc, char **argv) {
    char buffer[1025]; pam_handle_t *pamh = NULL;
    if (argc != 2 || !*argv[1] || strlen(argv[1]) > 64 || !fgets(buffer, sizeof buffer, stdin)) return 2;
    buffer[strcspn(buffer, "\r\n")] = 0; password = buffer;
    struct pam_conv conv = { conversation, NULL };
    int result = pam_start("ludus-web", argv[1], &conv, &pamh);
    if (result == PAM_SUCCESS) result = pam_authenticate(pamh, 0);
    if (result == PAM_SUCCESS) result = pam_acct_mgmt(pamh, 0);
    if (pamh) pam_end(pamh, result);
    memset(buffer, 0, sizeof buffer);
    return result == PAM_SUCCESS ? 0 : 1;
}
