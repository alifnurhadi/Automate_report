package main

import (
	"fmt"
)

func conc ( msg string , key int) {

	return msg, key
}


for i  range 1..10 {
	go conc ('mesesage',i)
}
