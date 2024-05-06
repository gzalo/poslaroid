#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <netinet/in.h>

#include <binder/IServiceManager.h>
#include <binder/IPCThreadState.h>
using namespace android;

#define PORT 6666
#define SOCKET_PATH "BT_Printer"
#define BINDER_PATH "PaxBtPrinter"
#define OPEN_FCN 1
#define CLOSE_FCN 2
#define WRITE_FCN 3

void connectUnixSocket(){
    int sockfd;
    struct sockaddr_un addr;

    // Create socket
    if ((sockfd = socket(AF_UNIX, SOCK_STREAM, 0)) == -1) {
        perror("socket");
        exit(EXIT_FAILURE);
    }

    // Clear address structur
    addr.sun_family = AF_UNIX;
    addr.sun_path[0] = '\0';
    strcpy(&addr.sun_path[1], SOCKET_PATH);
    int len_addr = offsetof(struct sockaddr_un, sun_path) + strlen(SOCKET_PATH) + 1;

    // Connect to the socket
    if (connect(sockfd, (struct sockaddr *)&addr, len_addr) == -1) {
        perror("connect");
        close(sockfd);
        exit(EXIT_FAILURE);
    }

    // Close the socket
    close(sockfd);
    printf("Connected and closed internal socket.\n");
}

int main(int argc, char *argv[]) {
    pid_t pid = fork();

    if (pid < 0) {
        fprintf(stderr, "Fork failed\n");
        exit(1);
    }

    if (pid > 0) {
        printf("Running service in background\n");
        exit(0);
    }

    if (setsid() < 0) {
        fprintf(stderr, "Error: setsid failed\n");
        exit(1);
    }

    freopen("/dev/null", "r", stdin);
    freopen("/tmp/printbridge.log", "a", stdout);
    freopen("/tmp/printbridge.log", "a", stderr);

    sp<IServiceManager> sm = defaultServiceManager();
    sp<IBinder> service = sm->checkService(String16(BINDER_PATH));

    if (service == NULL) {
        printf("Failed to get the binder\n");
        return -1;
    }

    int server_fd, new_socket, valread;
    struct sockaddr_in address;
    int opt = 1;
    int addrlen = sizeof(address);

    if ((server_fd = socket(AF_INET, SOCK_STREAM, 0)) == 0) {
        perror("socket failed");
        exit(EXIT_FAILURE);
    }

    if (setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR | SO_REUSEPORT,
                                                  &opt, sizeof(opt))) {
        perror("setsockopt");
        exit(EXIT_FAILURE);
    }
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(PORT);

    if (bind(server_fd, (struct sockaddr *)&address,
                                 sizeof(address))<0) {
        perror("bind failed");
        exit(EXIT_FAILURE);
    }

    if (listen(server_fd, 3) < 0) {
        perror("listen");
        exit(EXIT_FAILURE);
    }

    while(true){
        printf("Listening for connections on port %d\n", PORT);
        if ((new_socket = accept(server_fd, (struct sockaddr *)&address,
                        (socklen_t*)&addrlen))<0) {
            perror("accept");
            exit(EXIT_FAILURE);
        }

        printf("Accepted connection!\n");

        Parcel data, reply;
        data.writeInterfaceToken(service->getInterfaceDescriptor());
        service->transact(OPEN_FCN, data, &reply);

        connectUnixSocket();

        while (true) {
            char buffer[1024] = {0};
            int data_length = recv(new_socket, buffer, 1024, 0);

            if (data_length <= 0) {
                break;
            }
            buffer[data_length+1] = 0;

            /*printf("GOT data len %d\n", data_length);
            for(int i=0;i<data_length;i++) printf("%02x ", buffer[i]);
            printf("\n");*/
            
            Parcel data_stream, reply_stream;
            data_stream.writeInterfaceToken(String16("android.bluetooth.IPaxBtPrinter"));
            data_stream.writeInt32(data_length);
            data_stream.write(buffer, data_length);
            data_stream.writeInt32(0);
            data_stream.writeInt32(data_length);
            service->transact(WRITE_FCN, data_stream, &reply_stream);
            printf("Sent %d bytes.\n", data_length);
        }

        Parcel data2, reply2;
        data2.writeInterfaceToken(service->getInterfaceDescriptor());
        service->transact(CLOSE_FCN, data2, &reply2);

        close(new_socket);
        printf("Closing and starting new loop!");
    }
    close(server_fd);

    return 0;
}

