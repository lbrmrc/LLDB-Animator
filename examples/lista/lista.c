#include <stdio.h>
#include <stdlib.h>

struct nodo {
  int dato;
  struct nodo *next;
};

int somma(int *v, int n) {
  int s = 0;
  for (int i = 0; i < n; i++)
    s += v[i];
  return s;
}

int main() {
  int a, b;
  scanf("%d%d", &a, &b);
  struct nodo *p = malloc(sizeof(struct nodo));
  p->dato = a;
  p->next = malloc(sizeof(struct nodo));
  p->next->dato = b;
  p->next->next = NULL;
  int *arr = calloc(3, sizeof(int));
  arr[0] = a;
  printf("%d\n", somma(arr, 3));
  free(arr);
  free(p->next);
  free(p);
  return 0;
}
