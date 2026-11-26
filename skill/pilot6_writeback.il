;; pilot6_writeback.il — 在真实 OPA_D 副本上：n/p 都换器件 + 用 dbReplaceProp 写尺寸
(printf "\n=== PILOT6 START\n")
(load "/tmp/abConvertComponentParams.il")
(load "/tmp/abInvokeCdfCallbacks.il")

(unless (ddGetObj "port_pilot") (ddCreateLib "port_pilot" "/home/IC/port_pilot"))
(when (ddGetObj "port_pilot" "OPA_D") (ddDeleteObj (ddGetObj "port_pilot" "OPA_D")))

(let (src dst changed)
  (setq src (dbOpenCellViewByType "weekfour_last" "OPA_D" "schematic" "schematic" "r"))
  (setq dst (dbCopyCellView src "port_pilot" "OPA_D" "schematic"))
  (dbClose src)
  (dbClose dst)
  (setq dst (dbOpenCellViewByType "port_pilot" "OPA_D" "schematic" "schematic" "a"))
  (printf "copied: %d instances\n" (length dst~>instances))
  (setq changed (abConvertComponentParams "/tmp/pilot_conv6.config" dst))
  (printf "convert changed=%L\n" changed)
  ;; 统计转换后的 master
  (let (cnt)
    (setq cnt 0)
    (foreach i dst~>instances
      (when (equal i~>master~>libName "smic13mmrf_1233") (setq cnt (plus cnt 1))))
    (printf "converted instances=%d\n" cnt))
  ;; M1: dbReplaceProp（正确参数顺序：inst name propType value）
  (foreach i dst~>instances
    (when (equal i~>name "M1")
      (printf "M1 before: w=%L l=%L fingers=%L\n" i~>w i~>l i~>fingers)
      (errset (dbReplaceProp i "w" 'string "9u") t)
      (errset (dbReplaceProp i "l" 'string "500n") t)
      (errset (dbReplaceProp i "fingers" 'string "2") t)
      (printf "M1 after dbReplaceProp: dbGet w=%L l=%L fingers=%L\n"
              (dbGet i "w") (dbGet i "l") (dbGet i "fingers"))))
  ;; M3: 对比 dbSet
  (foreach i dst~>instances
    (when (equal i~>name "M3")
      (printf "M3 before: w=%L l=%L fingers=%L\n" i~>w i~>l i~>fingers)
      (dbSet i "w" "2u")
      (printf "M3 after dbSet: dbGet w=%L\n" (dbGet i "w"))))
  (schCheck dst)
  (dbSave dst)
  (dbClose dst))

;; 重开验证
(let (cv)
  (setq cv (dbOpenCellViewByType "port_pilot" "OPA_D" "schematic" "schematic" "r"))
  (foreach i cv~>instances
    (when (member i~>name (list "M1" "M3"))
      (printf "reopen %s: master=%s/%s w=%L l=%L fingers=%L\n"
              i~>name i~>master~>libName i~>master~>cellName i~>w i~>l i~>fingers)))
  (dbClose cv))

(printf "=== PILOT6 DONE\n")
(exit)